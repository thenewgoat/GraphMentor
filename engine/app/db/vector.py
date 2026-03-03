"""ChromaDB client singleton and per-course node-embedding collection helpers."""
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
    """Return (or create) the ``course_{id}_nodes`` collection for *course_id*.

    Hyphens in *course_id* are stripped so the name is a valid ChromaDB
    collection identifier.
    """
    client = get_chroma_client()
    collection_name = f"course_{course_id.replace('-', '')}_nodes"
    return client.get_or_create_collection(name=collection_name)


def upsert_node_embeddings(
    course_id: str,
    node_ids: list[str],
    embeddings: list[list[float]],
    metadatas: list[dict] | None = None,
) -> None:
    """Insert or update node embeddings in the course's ChromaDB collection."""
    if not node_ids:
        return
    collection = get_or_create_collection(course_id)
    kwargs: dict = {"ids": node_ids, "embeddings": embeddings}
    if metadatas is not None:
        kwargs["metadatas"] = metadatas
    collection.upsert(**kwargs)


def query_similar(
    course_id: str,
    query_embeddings: list[list[float]],
    n_results: int = 10,
) -> dict:
    """Return ChromaDB query-result dict for the nearest neighbours.

    Returns an empty-style result when the collection has no documents yet.
    """
    collection = get_or_create_collection(course_id)
    if collection.count() == 0:
        return {"ids": [[]], "distances": [[]], "metadatas": [[]], "documents": [[]]}
    return collection.query(query_embeddings=query_embeddings, n_results=n_results)


def delete_embeddings(course_id: str, node_ids: list[str]) -> None:
    """Delete node embeddings by ID list.  No-op when *node_ids* is empty."""
    if not node_ids:
        return
    collection = get_or_create_collection(course_id)
    collection.delete(ids=node_ids)


def delete_collection(course_id: str) -> None:
    """Delete the entire node-embedding collection for a course.

    No-op if the collection does not exist.
    """
    client = get_chroma_client()
    collection_name = f"course_{course_id.replace('-', '')}_nodes"
    try:
        client.delete_collection(name=collection_name)
    except (ValueError, chromadb.errors.ChromaError):
        # Collection doesn't exist — nothing to delete.
        pass
