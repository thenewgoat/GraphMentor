import logging

from openai import OpenAI

logger = logging.getLogger(__name__)


class OpenAIEmbedder:
    """Generate embeddings via OpenAI."""

    def __init__(
        self,
        api_key: str,
        model: str = "text-embedding-3-small",
        batch_size: int = 100,
    ):
        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.batch_size = batch_size

    def get_embeddings(self, texts: list[str]) -> list[list[float]]:
        """Get embeddings for a list of texts, batched by self.batch_size."""
        all_embeddings: list[list[float]] = []

        for i in range(0, len(texts), self.batch_size):
            batch = texts[i : i + self.batch_size]
            logger.info(f"Embedding batch {i // self.batch_size + 1} ({len(batch)} texts)")
            response = self.client.embeddings.create(input=batch, model=self.model)
            all_embeddings.extend([item.embedding for item in response.data])

        return all_embeddings
