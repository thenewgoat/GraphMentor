import hashlib
from pathlib import Path
from unittest.mock import MagicMock, patch
import fitz
import pytest

from app.services.ingest_pipeline import IngestPipeline
from app.models.course import Course
from app.models.sentence import Sentence


@pytest.fixture
def sample_pdf(tmp_path) -> Path:
    doc = fitz.open()
    page = doc.new_page(width=720, height=540)
    page.insert_text((50, 50), "Test Title", fontsize=24)
    page.insert_text((50, 120), "First sentence here. Second sentence here.", fontsize=14)
    pdf_path = tmp_path / "test.pdf"
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


class TestIngestPipeline:
    @patch("app.services.ingest_pipeline.OpenAIEmbedder")
    @patch("app.services.ingest_pipeline.get_chroma_client")
    def test_pipeline_creates_course_and_sentences(
        self, mock_chroma, mock_embedder_class, db, sample_pdf, tmp_path
    ):
        # Mock ChromaDB
        mock_collection = MagicMock()
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection
        mock_chroma.return_value = mock_client

        # Mock embedder
        mock_embedder = MagicMock()
        mock_embedder.format_text.side_effect = lambda s: s.text
        mock_embedder.get_embeddings.return_value = [[0.1] * 1536, [0.1] * 1536]
        mock_embedder_class.return_value = mock_embedder

        pipeline = IngestPipeline(
            db=db,
            upload_dir=tmp_path / "uploads",
            openai_api_key="fake",
        )
        result = pipeline.run(pdf_path=sample_pdf, title="Test Course")

        assert result["status"] == "complete"
        assert result["sentences_count"] == 2
        assert result["pages_processed"] == 1

        # Verify course in DB
        course = db.query(Course).filter_by(title="Test Course").first()
        assert course is not None
        assert course.ingestion_status == "complete"

        # Verify sentences in DB
        sentences = db.query(Sentence).filter_by(course_id=course.id).all()
        assert len(sentences) == 2

        # Verify ChromaDB was called
        mock_collection.add.assert_called_once()

    @patch("app.services.ingest_pipeline.OpenAIEmbedder")
    @patch("app.services.ingest_pipeline.get_chroma_client")
    def test_pipeline_rejects_duplicate_hash(
        self, mock_chroma, mock_embedder_class, db, sample_pdf, tmp_path
    ):
        pdf_hash = hashlib.sha256(sample_pdf.read_bytes()).hexdigest()
        existing = Course(
            title="Existing",
            source_pdf_path="/old.pdf",
            source_pdf_hash=pdf_hash,
            ingestion_status="complete",
        )
        db.add(existing)
        db.flush()

        pipeline = IngestPipeline(
            db=db,
            upload_dir=tmp_path / "uploads",
            openai_api_key="fake",
        )

        with pytest.raises(ValueError, match="duplicate"):
            pipeline.run(pdf_path=sample_pdf, title="Dupe Course")
