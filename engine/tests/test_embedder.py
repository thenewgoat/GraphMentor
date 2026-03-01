from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.services.embedder import OpenAIEmbedder
from app.services.extractors.models import RawSentence


class TestOpenAIEmbedder:
    def test_format_text_with_title(self):
        embedder = OpenAIEmbedder(api_key="fake")
        sentence = RawSentence(text="Hello world.", page=1, position=0, slide_title="Intro")
        assert embedder.format_text(sentence) == "[Intro] Hello world."

    def test_format_text_without_title(self):
        embedder = OpenAIEmbedder(api_key="fake")
        sentence = RawSentence(text="Hello world.", page=1, position=0, slide_title=None)
        assert embedder.format_text(sentence) == "Hello world."

    @patch("app.services.embedder.OpenAI")
    def test_get_embeddings_batches(self, mock_openai_class):
        mock_client = MagicMock()
        mock_openai_class.return_value = mock_client

        # Simulate OpenAI response
        mock_embedding = MagicMock()
        mock_embedding.embedding = [0.1] * 1536
        mock_response = MagicMock()
        mock_response.data = [mock_embedding, mock_embedding]
        mock_client.embeddings.create.return_value = mock_response

        embedder = OpenAIEmbedder(api_key="fake", batch_size=2)
        texts = ["Hello.", "World."]
        embeddings = embedder.get_embeddings(texts)

        assert len(embeddings) == 2
        assert len(embeddings[0]) == 1536
        mock_client.embeddings.create.assert_called_once()

    @patch("app.services.embedder.OpenAI")
    def test_get_embeddings_multiple_batches(self, mock_openai_class):
        mock_client = MagicMock()
        mock_openai_class.return_value = mock_client

        mock_embedding = MagicMock()
        mock_embedding.embedding = [0.1] * 1536
        mock_response = MagicMock()
        mock_response.data = [mock_embedding]
        mock_client.embeddings.create.return_value = mock_response

        embedder = OpenAIEmbedder(api_key="fake", batch_size=1)
        texts = ["A.", "B.", "C."]
        embeddings = embedder.get_embeddings(texts)

        assert len(embeddings) == 3
        assert mock_client.embeddings.create.call_count == 3
