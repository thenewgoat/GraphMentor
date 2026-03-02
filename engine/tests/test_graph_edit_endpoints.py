import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db.postgres import get_db
from app.models.course import Course
from app.models.node import Node, NodeEdge


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _make_course(db, hash_suffix="001"):
    course = Course(
        title="Test Course",
        source_pdf_path="/tmp/test.pdf",
        source_pdf_hash=f"edit_{hash_suffix}",
        ingestion_status="graph_ready",
    )
    db.add(course)
    db.flush()
    return course


class TestNodeCRUD:
    def test_create_node(self, client, db):
        course = _make_course(db, "create_node")
        response = client.post(
            f"/courses/{course.id}/nodes",
            json={"title": "New Topic"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["title"] == "New Topic"
        assert data["depth"] == 0
        assert "id" in data

    def test_create_node_course_not_found(self, client):
        response = client.post(
            f"/courses/{uuid.uuid4()}/nodes",
            json={"title": "Orphan"},
        )
        assert response.status_code == 404

    def test_update_node(self, client, db):
        course = _make_course(db, "update_node")
        node = Node(course_id=course.id, title="Old Title", depth=0, order_index=0)
        db.add(node)
        db.flush()

        response = client.patch(
            f"/courses/{course.id}/nodes/{node.id}",
            json={"title": "New Title"},
        )
        assert response.status_code == 200
        assert response.json()["title"] == "New Title"

    def test_update_node_not_found(self, client, db):
        course = _make_course(db, "update_404")
        response = client.patch(
            f"/courses/{course.id}/nodes/{uuid.uuid4()}",
            json={"title": "X"},
        )
        assert response.status_code == 404

    def test_delete_node(self, client, db):
        course = _make_course(db, "delete_node")
        node = Node(course_id=course.id, title="Doomed", depth=0, order_index=0)
        db.add(node)
        db.flush()
        node_id = node.id

        response = client.delete(f"/courses/{course.id}/nodes/{node_id}")
        assert response.status_code == 204

        assert db.get(Node, node_id) is None

    def test_delete_node_cascades_edges(self, client, db):
        course = _make_course(db, "delete_cascade")
        node_a = Node(course_id=course.id, title="A", depth=0, order_index=0)
        node_b = Node(course_id=course.id, title="B", depth=1, order_index=1)
        db.add_all([node_a, node_b])
        db.flush()
        edge = NodeEdge(parent_id=node_a.id, child_id=node_b.id)
        db.add(edge)
        db.flush()

        response = client.delete(f"/courses/{course.id}/nodes/{node_a.id}")
        assert response.status_code == 204
        remaining_edges = db.query(NodeEdge).filter(
            (NodeEdge.parent_id == node_a.id) | (NodeEdge.child_id == node_a.id)
        ).all()
        assert len(remaining_edges) == 0


class TestEdgeCRUD:
    def test_create_edge(self, client, db):
        course = _make_course(db, "create_edge")
        node_a = Node(course_id=course.id, title="A", depth=0, order_index=0)
        node_b = Node(course_id=course.id, title="B", depth=1, order_index=1)
        db.add_all([node_a, node_b])
        db.flush()

        response = client.post(
            f"/courses/{course.id}/edges",
            json={"parent_id": str(node_a.id), "child_id": str(node_b.id), "edge_type": "prerequisite"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["parent_id"] == str(node_a.id)

    def test_create_edge_self_loop_rejected(self, client, db):
        course = _make_course(db, "self_loop")
        node = Node(course_id=course.id, title="A", depth=0, order_index=0)
        db.add(node)
        db.flush()

        response = client.post(
            f"/courses/{course.id}/edges",
            json={"parent_id": str(node.id), "child_id": str(node.id), "edge_type": "prerequisite"},
        )
        assert response.status_code == 422

    def test_create_edge_duplicate_rejected(self, client, db):
        course = _make_course(db, "dup_edge")
        node_a = Node(course_id=course.id, title="A", depth=0, order_index=0)
        node_b = Node(course_id=course.id, title="B", depth=1, order_index=1)
        db.add_all([node_a, node_b])
        db.flush()
        db.add(NodeEdge(parent_id=node_a.id, child_id=node_b.id))
        db.flush()

        response = client.post(
            f"/courses/{course.id}/edges",
            json={"parent_id": str(node_a.id), "child_id": str(node_b.id), "edge_type": "prerequisite"},
        )
        assert response.status_code == 409

    def test_delete_edge(self, client, db):
        course = _make_course(db, "delete_edge")
        node_a = Node(course_id=course.id, title="A", depth=0, order_index=0)
        node_b = Node(course_id=course.id, title="B", depth=1, order_index=1)
        db.add_all([node_a, node_b])
        db.flush()
        db.add(NodeEdge(parent_id=node_a.id, child_id=node_b.id))
        db.flush()

        response = client.delete(f"/courses/{course.id}/edges/{node_a.id}/{node_b.id}")
        assert response.status_code == 204

    def test_delete_edge_not_found(self, client, db):
        course = _make_course(db, "delete_edge_404")
        response = client.delete(f"/courses/{course.id}/edges/{uuid.uuid4()}/{uuid.uuid4()}")
        assert response.status_code == 404
