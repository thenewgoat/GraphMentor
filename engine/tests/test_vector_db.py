"""Tests for ChromaDB node-embedding helpers (in-memory client)."""
import uuid
from unittest.mock import patch

import chromadb
import pytest

from app.db.vector import (
    delete_collection,
    delete_embeddings,
    get_or_create_collection,
    query_similar,
    upsert_node_embeddings,
)


@pytest.fixture
def chroma_client():
    """In-memory ChromaDB client, isolated per test via unique course IDs."""
    return chromadb.Client()


@pytest.fixture(autouse=True)
def _patch_client(chroma_client):
    """Ensure every call to ``get_chroma_client()`` returns the in-memory client."""
    with patch("app.db.vector.get_chroma_client", return_value=chroma_client):
        yield


@pytest.fixture
def course_id():
    """Unique course ID per test to avoid cross-test collection collisions."""
    return str(uuid.uuid4())


# ── get_or_create_collection ────────────────────────────────────────────

class TestGetOrCreateCollection:
    def test_returns_collection_with_nodes_suffix(self):
        coll = get_or_create_collection("abc-def-123")
        assert coll.name == "course_abcdef123_nodes"

    def test_hyphens_stripped_from_course_id(self):
        coll = get_or_create_collection("a-b-c")
        assert coll.name == "course_abc_nodes"

    def test_idempotent(self, course_id):
        coll1 = get_or_create_collection(course_id)
        coll2 = get_or_create_collection(course_id)
        assert coll1.name == coll2.name


# ── upsert_node_embeddings ──────────────────────────────────────────────

class TestUpsertNodeEmbeddings:
    def test_upsert_creates_entries(self, course_id):
        upsert_node_embeddings(
            course_id,
            node_ids=["n1", "n2"],
            embeddings=[[0.1, 0.2], [0.3, 0.4]],
        )
        coll = get_or_create_collection(course_id)
        assert coll.count() == 2

    def test_upsert_with_metadata(self, course_id):
        upsert_node_embeddings(
            course_id,
            node_ids=["n1"],
            embeddings=[[0.1, 0.2]],
            metadatas=[{"label": "Algebra"}],
        )
        result = get_or_create_collection(course_id).get(
            ids=["n1"], include=["metadatas"]
        )
        assert result["metadatas"][0]["label"] == "Algebra"

    def test_upsert_overwrites_existing(self, course_id):
        upsert_node_embeddings(
            course_id,
            node_ids=["n1"],
            embeddings=[[0.1, 0.2]],
            metadatas=[{"label": "old"}],
        )
        upsert_node_embeddings(
            course_id,
            node_ids=["n1"],
            embeddings=[[0.9, 0.8]],
            metadatas=[{"label": "new"}],
        )
        coll = get_or_create_collection(course_id)
        assert coll.count() == 1
        result = coll.get(ids=["n1"], include=["metadatas"])
        assert result["metadatas"][0]["label"] == "new"

    def test_noop_on_empty_node_ids(self, course_id):
        upsert_node_embeddings(course_id, node_ids=[], embeddings=[])
        coll = get_or_create_collection(course_id)
        assert coll.count() == 0

    def test_upsert_without_metadata(self, course_id):
        upsert_node_embeddings(
            course_id,
            node_ids=["n1"],
            embeddings=[[0.5, 0.5]],
        )
        coll = get_or_create_collection(course_id)
        assert coll.count() == 1


# ── query_similar ───────────────────────────────────────────────────────

class TestQuerySimilar:
    def test_returns_nearest_neighbours(self, course_id):
        upsert_node_embeddings(
            course_id,
            node_ids=["n1", "n2", "n3"],
            embeddings=[[1.0, 0.0], [0.0, 1.0], [0.5, 0.5]],
        )
        result = query_similar(course_id, query_embeddings=[[1.0, 0.0]], n_results=2)
        assert "ids" in result
        # Nearest to [1, 0] should be n1
        assert result["ids"][0][0] == "n1"
        assert len(result["ids"][0]) == 2

    def test_empty_collection_returns_empty_result(self, course_id):
        result = query_similar(course_id, query_embeddings=[[0.1, 0.2]])
        assert result["ids"] == [[]]
        assert result["distances"] == [[]]
        assert result["metadatas"] == [[]]
        assert result["documents"] == [[]]

    def test_n_results_capped_to_collection_size(self, course_id):
        upsert_node_embeddings(
            course_id,
            node_ids=["n1"],
            embeddings=[[1.0, 0.0]],
        )
        result = query_similar(
            course_id, query_embeddings=[[1.0, 0.0]], n_results=100
        )
        assert len(result["ids"][0]) == 1

    def test_returns_metadata_in_results(self, course_id):
        upsert_node_embeddings(
            course_id,
            node_ids=["n1"],
            embeddings=[[1.0, 0.0]],
            metadatas=[{"label": "Algebra"}],
        )
        result = query_similar(course_id, query_embeddings=[[1.0, 0.0]], n_results=1)
        assert result["metadatas"][0][0]["label"] == "Algebra"

    def test_multiple_query_embeddings(self, course_id):
        upsert_node_embeddings(
            course_id,
            node_ids=["n1", "n2"],
            embeddings=[[1.0, 0.0], [0.0, 1.0]],
        )
        result = query_similar(
            course_id,
            query_embeddings=[[1.0, 0.0], [0.0, 1.0]],
            n_results=1,
        )
        assert len(result["ids"]) == 2
        assert result["ids"][0][0] == "n1"
        assert result["ids"][1][0] == "n2"


# ── delete_embeddings ──────────────────────────────────────────────────

class TestDeleteEmbeddings:
    def test_deletes_specified_node_ids(self, course_id):
        upsert_node_embeddings(
            course_id,
            node_ids=["n1", "n2", "n3"],
            embeddings=[[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]],
        )
        delete_embeddings(course_id, node_ids=["n1", "n3"])
        coll = get_or_create_collection(course_id)
        assert coll.count() == 1
        remaining = coll.get(ids=["n2"])
        assert len(remaining["ids"]) == 1

    def test_noop_on_empty_list(self, course_id, chroma_client):
        delete_embeddings(course_id, node_ids=[])
        clean_name = f"course_{course_id.replace('-', '')}_nodes"
        names = [c.name for c in chroma_client.list_collections()]
        assert clean_name not in names

    def test_delete_all_entries(self, course_id):
        upsert_node_embeddings(
            course_id,
            node_ids=["n1", "n2"],
            embeddings=[[0.1, 0.2], [0.3, 0.4]],
        )
        delete_embeddings(course_id, node_ids=["n1", "n2"])
        coll = get_or_create_collection(course_id)
        assert coll.count() == 0


# ── delete_collection ──────────────────────────────────────────────────

class TestDeleteCollection:
    def test_deletes_existing_collection(self, course_id, chroma_client):
        upsert_node_embeddings(
            course_id,
            node_ids=["n1"],
            embeddings=[[0.1, 0.2]],
        )
        clean_name = f"course_{course_id.replace('-', '')}_nodes"
        assert clean_name in [c.name for c in chroma_client.list_collections()]

        delete_collection(course_id)
        assert clean_name not in [c.name for c in chroma_client.list_collections()]

    def test_noop_when_collection_does_not_exist(self):
        # Should not raise
        delete_collection(str(uuid.uuid4()))

    def test_double_delete_is_safe(self, course_id):
        upsert_node_embeddings(
            course_id,
            node_ids=["n1"],
            embeddings=[[0.1, 0.2]],
        )
        delete_collection(course_id)
        # Second delete should be a no-op
        delete_collection(course_id)
