import fitz
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def sample_pdf_bytes(tmp_path) -> tuple[Path, bytes]:
    doc = fitz.open()
    page = doc.new_page(width=720, height=540)
    page.insert_text((50, 50), "Endpoint Test", fontsize=24)
    page.insert_text((50, 120), "A sentence for testing.", fontsize=14)
    pdf_path = tmp_path / "endpoint_test.pdf"
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path, pdf_path.read_bytes()


class TestIngestEndpoint:
    @patch("app.routers.ingest.IngestPipeline")
    def test_upload_success(self, mock_pipeline_class, client, sample_pdf_bytes):
        _, pdf_bytes = sample_pdf_bytes

        mock_pipeline = MagicMock()
        mock_pipeline.run.return_value = {
            "course_id": "fake-uuid",
            "title": "My Course",
            "sentences_count": 5,
            "pages_processed": 2,
            "status": "complete",
        }
        mock_pipeline_class.return_value = mock_pipeline

        response = client.post(
            "/ingest/upload",
            data={"title": "My Course"},
            files={"file": ("slides.pdf", pdf_bytes, "application/pdf")},
        )

        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "complete"
        assert body["sentences_count"] == 5

    def test_upload_rejects_non_pdf(self, client):
        response = client.post(
            "/ingest/upload",
            data={"title": "Bad File"},
            files={"file": ("notes.txt", b"hello", "text/plain")},
        )
        assert response.status_code == 422
