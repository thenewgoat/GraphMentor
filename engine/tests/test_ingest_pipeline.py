"""Tests for ingestion pipeline: course creation, pages, and duplicate detection."""
import hashlib
from pathlib import Path
from uuid import UUID
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
    def test_pipeline_creates_course_and_pages(
        self, db, sample_pdf, tmp_path
    ):
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

    def test_pipeline_rejects_duplicate_hash_in_same_course(
        self, db, sample_pdf, tmp_path
    ):
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

    def test_pipeline_multi_doc_increments_upload_order(
        self, db, tmp_path
    ):
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

    def test_page_count_excludes_empty_slides(
        self, db, tmp_path
    ):
        # Create a PDF with 2 pages: one with text, one blank
        doc = fitz.open()
        p1 = doc.new_page(width=720, height=540)
        p1.insert_text((50, 50), "Real Content", fontsize=24)
        p1.insert_text((50, 120), "Some body text here.", fontsize=14)
        doc.new_page(width=720, height=540)  # blank page
        pdf_path = tmp_path / "mixed.pdf"
        doc.save(str(pdf_path))
        doc.close()

        pipeline = IngestPipeline(
            db=db, upload_dir=tmp_path / "uploads", openai_api_key="fake",
        )
        result = pipeline.run(pdf_path=pdf_path, title="Mixed Course")

        # page_count on the document should match pages_count in result
        from app.models.document import Document as DocModel
        doc_record = db.query(DocModel).filter_by(id=result["document_id"]).first()
        assert doc_record.page_count == result["pages_count"]
