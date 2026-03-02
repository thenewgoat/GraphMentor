"""Tests for ingestion pipeline: course creation, pages, and duplicate detection."""
import hashlib
from pathlib import Path
from unittest.mock import MagicMock, patch
import fitz
import pytest

from app.services.ingest_pipeline import IngestPipeline
from app.models.course import Course
from app.models.document import Document, Page


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
    def test_pipeline_creates_course_and_pages(
        self, mock_chroma, mock_embedder_class, db, sample_pdf, tmp_path
    ):
        mock_collection = MagicMock()
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection
        mock_chroma.return_value = mock_client

        mock_embedder = MagicMock()
        mock_embedder.get_embeddings.return_value = [[0.1] * 1536]
        mock_embedder_class.return_value = mock_embedder

        pipeline = IngestPipeline(
            db=db, upload_dir=tmp_path / "uploads", openai_api_key="fake",
        )
        result = pipeline.run(pdf_path=sample_pdf, title="Test Course")

        assert result["status"] == "complete"
        assert result["pages_count"] == 1
        assert "document_id" in result

        course = db.query(Course).filter_by(title="Test Course").first()
        assert course is not None
        assert course.ingestion_status == "complete"

        doc = db.query(Document).filter_by(course_id=course.id).first()
        assert doc is not None
        assert doc.ingestion_status == "complete"
        assert doc.upload_order == 1

        pages = db.query(Page).filter_by(document_id=doc.id).all()
        assert len(pages) == 1

        mock_collection.add.assert_called_once()

    @patch("app.services.ingest_pipeline.OpenAIEmbedder")
    @patch("app.services.ingest_pipeline.get_chroma_client")
    def test_pipeline_rejects_duplicate_hash_in_same_course(
        self, mock_chroma, mock_embedder_class, db, sample_pdf, tmp_path
    ):
        mock_collection = MagicMock()
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection
        mock_chroma.return_value = mock_client

        mock_embedder = MagicMock()
        mock_embedder.get_embeddings.return_value = [[0.1] * 1536]
        mock_embedder_class.return_value = mock_embedder

        pipeline = IngestPipeline(
            db=db, upload_dir=tmp_path / "uploads", openai_api_key="fake",
        )

        # First upload creates course
        result = pipeline.run(pdf_path=sample_pdf, title="Test Course")
        course_id = result["course_id"]

        # Second upload of same PDF to same course should fail
        from uuid import UUID
        with pytest.raises(ValueError, match="duplicate"):
            pipeline.run(pdf_path=sample_pdf, title="Dup Doc", course_id=UUID(course_id))

    @patch("app.services.ingest_pipeline.OpenAIEmbedder")
    @patch("app.services.ingest_pipeline.get_chroma_client")
    def test_pipeline_multi_doc_increments_upload_order(
        self, mock_chroma, mock_embedder_class, db, tmp_path
    ):
        mock_collection = MagicMock()
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection
        mock_chroma.return_value = mock_client

        mock_embedder = MagicMock()
        mock_embedder.get_embeddings.return_value = [[0.1] * 1536]
        mock_embedder_class.return_value = mock_embedder

        # Create two different PDFs
        pdfs = []
        for i in range(2):
            doc = fitz.open()
            page = doc.new_page(width=720, height=540)
            page.insert_text((50, 50), f"Title {i}", fontsize=24)
            page.insert_text((50, 120), f"Content for document {i}.", fontsize=14)
            pdf_path = tmp_path / f"doc{i}.pdf"
            doc.save(str(pdf_path))
            doc.close()
            pdfs.append(pdf_path)

        pipeline = IngestPipeline(
            db=db, upload_dir=tmp_path / "uploads", openai_api_key="fake",
        )

        r1 = pipeline.run(pdf_path=pdfs[0], title="Course")
        from uuid import UUID
        r2 = pipeline.run(pdf_path=pdfs[1], title="Doc 2", course_id=UUID(r1["course_id"]))

        assert r1["upload_order"] == 1
        assert r2["upload_order"] == 2
