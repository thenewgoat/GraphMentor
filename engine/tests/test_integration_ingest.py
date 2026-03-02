"""Integration test: runs the full pipeline with mocked OpenAI only."""
import fitz
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

from app.services.ingest_pipeline import IngestPipeline
from app.models.course import Course
from app.models.document import Document, Page


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
        mock_collection = MagicMock()
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection
        mock_chroma.return_value = mock_client

        mock_embedder = MagicMock()
        mock_embedder.get_embeddings.side_effect = lambda texts: [[0.1] * 1536] * len(texts)
        mock_embedder_class.return_value = mock_embedder

        pipeline = IngestPipeline(
            db=db, upload_dir=tmp_path / "uploads", openai_api_key="fake"
        )
        result = pipeline.run(pdf_path=multi_slide_pdf, title="ML Course")

        # Pipeline result
        assert result["status"] == "complete"
        assert result["pages_count"] == 2  # slide 3 is empty

        # Course in DB
        course = db.query(Course).filter_by(title="ML Course").first()
        assert course.ingestion_status == "complete"

        # Document in DB
        doc = db.query(Document).filter_by(course_id=course.id).first()
        assert doc is not None
        assert doc.page_count == 2  # only non-empty slides counted
        assert doc.upload_order == 1

        # Pages in DB (only non-empty slides)
        pages = (
            db.query(Page)
            .filter_by(document_id=doc.id)
            .order_by(Page.page_number)
            .all()
        )
        assert len(pages) == 2

        # Page 1
        assert "Machine learning" in pages[0].body
        assert pages[0].slide_title is not None

        # Page 2
        assert "Dr. Smith" in pages[1].body

        # ChromaDB received 2 pages
        call_args = mock_collection.add.call_args
        assert len(call_args.kwargs["ids"]) == 2

    @patch("app.services.ingest_pipeline.OpenAIEmbedder")
    @patch("app.services.ingest_pipeline.get_chroma_client")
    def test_rollback_on_failure(self, mock_chroma, mock_embedder_class, db, multi_slide_pdf, tmp_path):
        mock_embedder = MagicMock()
        mock_embedder.get_embeddings.side_effect = RuntimeError("API down")
        mock_embedder_class.return_value = mock_embedder

        pipeline = IngestPipeline(
            db=db, upload_dir=tmp_path / "uploads", openai_api_key="fake"
        )

        with pytest.raises(RuntimeError, match="API down"):
            pipeline.run(pdf_path=multi_slide_pdf, title="Fail Course")

        # Course should exist (created before document fails) but document should be deleted
        course = db.query(Course).filter_by(title="Fail Course").first()
        if course:
            docs = db.query(Document).filter_by(course_id=course.id).all()
            assert len(docs) == 0
