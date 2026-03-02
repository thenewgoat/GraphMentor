import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


class TestExtractEndpoint:
    @patch("app.routers.extract.GraphBuilder")
    def test_extract_success(self, mock_builder_class, client, db):
        mock_builder = MagicMock()
        mock_builder.run.return_value = {
            "course_id": str(uuid.uuid4()),
            "nodes_created": 5,
            "edges_created": 4,
            "node_sentences_created": 12,
        }
        mock_builder_class.return_value = mock_builder

        response = client.post(f"/extract/topics/{uuid.uuid4()}?max_depth=3")
        assert response.status_code == 201
        body = response.json()
        assert body["nodes_created"] == 5
        assert body["edges_created"] == 4

    @patch("app.routers.extract.GraphBuilder")
    def test_extract_course_not_found(self, mock_builder_class, client):
        mock_builder = MagicMock()
        mock_builder.run.side_effect = ValueError("Course fake not found")
        mock_builder_class.return_value = mock_builder

        response = client.post(f"/extract/topics/{uuid.uuid4()}")
        assert response.status_code == 404

    @patch("app.routers.extract.GraphBuilder")
    def test_extract_wrong_status(self, mock_builder_class, client):
        mock_builder = MagicMock()
        mock_builder.run.side_effect = ValueError("has status 'processing', expected")
        mock_builder_class.return_value = mock_builder

        response = client.post(f"/extract/topics/{uuid.uuid4()}")
        assert response.status_code == 409
