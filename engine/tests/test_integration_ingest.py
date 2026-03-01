"""Integration test: runs the full pipeline with mocked OpenAI only."""
import fitz
import hashlib
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

from app.services.ingest_pipeline import IngestPipeline
from app.models.course import Course
from app.models.sentence import Sentence


@pytest.fixture
def multi_slide_pdf(tmp_path) -> Path:
    doc = fitz.open()

    # Slide 1
    page = doc.new_page(width=720, height=540)
    page.insert_text((50, 50), "Machine Learning Basics", fontsize=24)
    page.insert_text((50, 120), "Machine learning is a subset of AI.", fontsize=14)
    page.insert_text((50, 150), "It enables computers to learn from data.", fontsize=14)

    # Slide 2
    page = doc.new_page(width=720, height=540)
    page.insert_text((50, 50), "Dr. Smith's Approach", fontsize=24)
    page.insert_text((50, 120), "Dr. Smith proposed a novel algorithm in 2019.", fontsize=14)
    page.insert_text((50, 150), "The algorithm runs in O(n log n) time.", fontsize=14)
    page.insert_text((50, 180), "It outperforms e.g. naive implementations.", fontsize=14)

    # Slide 3 — empty (image-only)
    doc.new_page(width=720, height=540)

    pdf_path = tmp_path / "ml_slides.pdf"
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


class TestFullPipeline:
    @patch("app.services.ingest_pipeline.OpenAIEmbedder")
    @patch("app.services.ingest_pipeline.get_chroma_client")
    def test_end_to_end(self, mock_chroma, mock_embedder_class, db, multi_slide_pdf, tmp_path):
        # Mock ChromaDB
        mock_collection = MagicMock()
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection
        mock_chroma.return_value = mock_client

        # Mock embedder — return correct number of embeddings
        mock_embedder = MagicMock()
        mock_embedder.format_text.side_effect = lambda s: s.text
        mock_embedder.get_embeddings.side_effect = lambda texts: [[0.1] * 1536] * len(texts)
        mock_embedder_class.return_value = mock_embedder

        pipeline = IngestPipeline(
            db=db, upload_dir=tmp_path / "uploads", openai_api_key="fake"
        )
        result = pipeline.run(pdf_path=multi_slide_pdf, title="ML Course")

        # Pipeline result
        assert result["status"] == "complete"
        assert result["pages_processed"] == 2  # slide 3 is empty
        assert result["sentences_count"] == 5  # 2 + 3

        # Course in DB
        course = db.query(Course).filter_by(title="ML Course").first()
        assert course.ingestion_status == "complete"
        assert course.source_pdf_hash == hashlib.sha256(multi_slide_pdf.read_bytes()).hexdigest()

        # Sentences in DB
        sentences = (
            db.query(Sentence)
            .filter_by(course_id=course.id)
            .order_by(Sentence.page, Sentence.position)
            .all()
        )
        assert len(sentences) == 5

        # Page 1 sentences
        p1 = [s for s in sentences if s.page == 1]
        assert len(p1) == 2
        assert "Machine learning" in p1[0].text
        assert p1[0].slide_title is not None

        # Page 2 sentences — abbreviations handled
        p2 = [s for s in sentences if s.page == 2]
        assert len(p2) == 3
        assert any("Dr. Smith" in s.text for s in p2)
        assert any("e.g." in s.text for s in p2)

        # ChromaDB received all 5 sentences
        call_args = mock_collection.add.call_args
        assert len(call_args.kwargs["ids"]) == 5

    @patch("app.services.ingest_pipeline.OpenAIEmbedder")
    @patch("app.services.ingest_pipeline.get_chroma_client")
    def test_rollback_on_failure(self, mock_chroma, mock_embedder_class, db, multi_slide_pdf, tmp_path):
        # Mock embedder to fail
        mock_embedder = MagicMock()
        mock_embedder.format_text.side_effect = lambda s: s.text
        mock_embedder.get_embeddings.side_effect = RuntimeError("API down")
        mock_embedder_class.return_value = mock_embedder

        pipeline = IngestPipeline(
            db=db, upload_dir=tmp_path / "uploads", openai_api_key="fake"
        )

        with pytest.raises(RuntimeError, match="API down"):
            pipeline.run(pdf_path=multi_slide_pdf, title="Fail Course")

        # Course should not exist
        assert db.query(Course).filter_by(title="Fail Course").first() is None
