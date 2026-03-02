"""Tests for ChromaDB vector database helpers."""
from unittest.mock import MagicMock, patch

from app.db.vector import delete_embeddings


class TestDeleteEmbeddings:
    @patch("app.db.vector.get_chroma_client")
    def test_deletes_page_ids_from_collection(self, mock_get_client):
        mock_collection = MagicMock()
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection
        mock_get_client.return_value = mock_client

        delete_embeddings(course_id="abc-123", page_ids=["p1", "p2"])

        mock_client.get_or_create_collection.assert_called_once_with(
            name="course_abc123_pages"
        )
        mock_collection.delete.assert_called_once_with(ids=["p1", "p2"])

    @patch("app.db.vector.get_chroma_client")
    def test_no_op_on_empty_page_ids(self, mock_get_client):
        delete_embeddings(course_id="abc-123", page_ids=[])
        mock_get_client.assert_not_called()
