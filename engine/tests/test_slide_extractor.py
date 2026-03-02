"""Tests for PDF slide extraction, title detection, and file validation."""
import fitz  # pymupdf
from pathlib import Path
import tempfile
import pytest

from app.services.extractors.slide_extractor import SlideExtractor


@pytest.fixture
def sample_pdf(tmp_path) -> Path:
    """Create a minimal PDF with 3 slides for testing."""
    doc = fitz.open()

    # Slide 1: title + body
    page = doc.new_page(width=720, height=540)
    page.insert_text((50, 50), "Introduction to Testing", fontsize=24)
    page.insert_text((50, 120), "This is the first bullet point.", fontsize=14)
    page.insert_text((50, 150), "Here is another important concept.", fontsize=14)

    # Slide 2: title + body with abbreviation
    page = doc.new_page(width=720, height=540)
    page.insert_text((50, 50), "Dr. Smith's Method", fontsize=24)
    page.insert_text((50, 120), "The algorithm runs in O(n) time.", fontsize=14)

    # Slide 3: no text (image-only slide simulation)
    doc.new_page(width=720, height=540)

    pdf_path = tmp_path / "test_slides.pdf"
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


class TestSlideExtractor:
    def test_supported_extensions(self):
        extractor = SlideExtractor()
        assert ".pdf" in extractor.supported_extensions

    def test_extract_returns_slides(self, sample_pdf):
        extractor = SlideExtractor()
        slides = extractor.extract(sample_pdf)
        # Slide 3 is empty, should be skipped or have empty body
        non_empty = [s for s in slides if s.body.strip()]
        assert len(non_empty) == 2

    def test_slide_has_title(self, sample_pdf):
        extractor = SlideExtractor()
        slides = extractor.extract(sample_pdf)
        assert slides[0].title is not None
        assert "Introduction" in slides[0].title or "Testing" in slides[0].title

    def test_slide_has_body(self, sample_pdf):
        extractor = SlideExtractor()
        slides = extractor.extract(sample_pdf)
        assert "bullet point" in slides[0].body

    def test_slide_pages_are_1_indexed(self, sample_pdf):
        extractor = SlideExtractor()
        slides = extractor.extract(sample_pdf)
        assert slides[0].page == 1
        assert slides[1].page == 2

    def test_validate_file_rejects_non_pdf(self, tmp_path):
        txt_file = tmp_path / "notes.txt"
        txt_file.write_text("hello")
        extractor = SlideExtractor()
        with pytest.raises(ValueError, match="Unsupported file type"):
            extractor.validate_file(txt_file)

    def test_validate_file_rejects_missing(self, tmp_path):
        extractor = SlideExtractor()
        with pytest.raises(FileNotFoundError):
            extractor.validate_file(tmp_path / "nonexistent.pdf")
