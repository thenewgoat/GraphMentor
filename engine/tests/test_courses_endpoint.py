"""Tests for course, graph, documents, references, nodes, and edges endpoints."""
import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db.postgres import get_db
from app.models.course import Course
from app.models.node import Node, NodeEdge
from app.models.document import Document, Page, NodePage


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


class TestCoursesEndpoint:
    def test_list_courses_empty(self, client):
        response = client.get("/courses")
        assert response.status_code == 200
        assert response.json() == []

    def test_list_courses_returns_courses(self, client, db):
        course = Course(title="Test Course")
        db.add(course)
        db.flush()

        response = client.get("/courses")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["title"] == "Test Course"
        assert data[0]["ingestion_status"] == "pending"
        assert data[0]["document_count"] == 0

    def test_get_course_found(self, client, db):
        course = Course(title="Test Course")
        db.add(course)
        db.flush()

        response = client.get(f"/courses/{course.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "Test Course"
        assert "id" in data
        assert "document_count" in data

    def test_get_course_not_found(self, client):
        response = client.get(f"/courses/{uuid.uuid4()}")
        assert response.status_code == 404


class TestGraphEndpoint:
    def test_get_graph_empty(self, client, db):
        course = Course(title="Empty Course", ingestion_status="graph_ready")
        db.add(course)
        db.flush()

        response = client.get(f"/courses/{course.id}/graph")
        assert response.status_code == 200
        data = response.json()
        assert data["nodes"] == []
        assert data["edges"] == []

    def test_get_graph_with_data(self, client, db):
        course = Course(title="Graph Course", ingestion_status="graph_ready")
        db.add(course)
        db.flush()

        node_a = Node(course_id=course.id, title="Intro", depth=0, order_index=0)
        node_b = Node(course_id=course.id, title="Basics", depth=1, order_index=1)
        db.add_all([node_a, node_b])
        db.flush()

        edge = NodeEdge(parent_id=node_a.id, child_id=node_b.id, edge_type="prerequisite")
        db.add(edge)

        doc = Document(
            course_id=course.id, title="Lec", filename="l.pdf",
            file_path="/tmp/l.pdf", file_hash="graphtest001", upload_order=1,
        )
        db.add(doc)
        db.flush()

        page = Page(
            document_id=doc.id, course_id=course.id,
            page_number=1, global_page=1,
            slide_title="Slide 1", body="Hello world",
        )
        db.add(page)
        db.flush()

        np = NodePage(node_id=node_a.id, page_id=page.id)
        db.add(np)
        db.flush()

        response = client.get(f"/courses/{course.id}/graph")
        assert response.status_code == 200
        data = response.json()
        assert len(data["nodes"]) == 2
        assert len(data["edges"]) == 1
        assert data["edges"][0]["edge_type"] == "prerequisite"
        # Check pages are included in node
        intro_node = next(n for n in data["nodes"] if n["title"] == "Intro")
        assert len(intro_node["pages"]) == 1
        assert intro_node["pages"][0]["body"] == "Hello world"

    def test_get_graph_course_not_found(self, client):
        response = client.get(f"/courses/{uuid.uuid4()}/graph")
        assert response.status_code == 404


class TestDocumentsEndpoint:
    def test_list_documents(self, client, db):
        course = Course(title="Doc Course")
        db.add(course)
        db.flush()

        doc = Document(
            course_id=course.id, title="Lec 1", filename="lec1.pdf",
            file_path="/tmp/lec1.pdf", file_hash="doctest001", upload_order=1,
            page_count=5, ingestion_status="complete",
        )
        db.add(doc)
        db.flush()

        response = client.get(f"/courses/{course.id}/documents")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["title"] == "Lec 1"
        assert data[0]["page_count"] == 5


class TestReferencesEndpoint:
    def test_list_references_empty(self, client, db):
        course = Course(title="Ref Course")
        db.add(course)
        db.flush()

        response = client.get(f"/courses/{course.id}/references")
        assert response.status_code == 200
        assert response.json() == []

    def test_create_and_delete_reference(self, client, db):
        course = Course(title="Ref Course 2")
        db.add(course)
        db.flush()

        # Create
        response = client.post(
            f"/courses/{course.id}/references",
            json={"ref_type": "book", "title": "CLRS", "author": "Cormen"},
        )
        assert response.status_code == 201
        ref_id = response.json()["id"]

        # Verify it exists
        response = client.get(f"/courses/{course.id}/references")
        assert len(response.json()) == 1

        # Delete
        response = client.delete(f"/courses/{course.id}/references/{ref_id}")
        assert response.status_code == 204

        # Verify deleted
        response = client.get(f"/courses/{course.id}/references")
        assert len(response.json()) == 0
