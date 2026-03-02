"""ChromaDB client singleton and per-course vector collection factory."""
import chromadb

from app.config import settings

_client: chromadb.ClientAPI | None = None


def get_chroma_client() -> chromadb.ClientAPI:
    global _client
    if _client is None:
        if settings.chromadb_mode == "http":
            _client = chromadb.HttpClient(
                host=settings.chromadb_host,
                port=settings.chromadb_port,
            )
        else:
            _client = chromadb.PersistentClient(path=settings.chromadb_path)
    return _client


def get_or_create_collection(course_id: str) -> chromadb.Collection:
    client = get_chroma_client()
    collection_name = f"course_{course_id.replace('-', '')}_sentences"
    return client.get_or_create_collection(name=collection_name)


def delete_embeddings(course_id: str, page_ids: list[str]) -> None:
    """Delete page embeddings from a course's ChromaDB collection."""
    if not page_ids:
        return
    client = get_chroma_client()
    collection_name = f"course_{course_id.replace('-', '')}_pages"
    collection = client.get_or_create_collection(name=collection_name)
    collection.delete(ids=page_ids)
