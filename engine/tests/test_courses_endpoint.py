"""Tests for course, graph, documents, references, nodes, and edges endpoints."""
import uuid
from unittest.mock import patch

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

        edge = NodeEdge(parent_id=node_a.id, child_id=node_b.id, edge_category="dependency", edge_label="prerequisite for")
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
        assert data["edges"][0]["edge_category"] == "dependency"
        assert data["edges"][0]["edge_label"] == "prerequisite for"
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


class TestDeleteDocumentEndpoint:
    def test_delete_document_returns_204(self, client, db):
        course = Course(title="Del Doc Course")
        db.add(course)
        db.flush()

        doc = Document(
            course_id=course.id, title="To Delete", filename="del.pdf",
            file_path="/tmp/del.pdf", file_hash="deltest001", upload_order=1,
            page_count=1, ingestion_status="complete",
        )
        db.add(doc)
        db.flush()

        page = Page(
            document_id=doc.id, course_id=course.id,
            page_number=1, global_page=1,
            slide_title="S1", body="Content",
        )
        db.add(page)
        db.flush()

        # Create a node linked to the page so it becomes an orphan after doc deletion
        node = Node(course_id=course.id, title="Orphan Topic", depth=1, order_index=0)
        db.add(node)
        db.flush()
        db.add(NodePage(node_id=node.id, page_id=page.id))
        db.flush()

        with patch("app.routers.courses.delete_embeddings") as mock_del:
            response = client.delete(f"/courses/{course.id}/documents/{doc.id}")

        assert response.status_code == 204

        # Document and pages should be gone
        assert db.query(Document).filter_by(id=doc.id).first() is None
        assert db.query(Page).filter_by(document_id=doc.id).all() == []

        # Orphan node should be gone
        assert db.query(Node).filter_by(id=node.id).first() is None

        # Embeddings cleanup was called for orphan nodes
        mock_del.assert_called_once_with(str(course.id), [str(node.id)])

    def test_delete_document_removes_orphan_nodes(self, client, db):
        course = Course(title="Orphan Course")
        db.add(course)
        db.flush()

        doc = Document(
            course_id=course.id, title="Only Doc", filename="only.pdf",
            file_path="/tmp/only.pdf", file_hash="orphantest001", upload_order=1,
            page_count=1, ingestion_status="complete",
        )
        db.add(doc)
        db.flush()

        page = Page(
            document_id=doc.id, course_id=course.id,
            page_number=1, global_page=1,
            slide_title="S1", body="Content",
        )
        db.add(page)
        db.flush()

        # Create a node linked only to this page (will become orphan)
        orphan_node = Node(course_id=course.id, title="Orphan Topic", depth=1, order_index=0)
        db.add(orphan_node)
        db.flush()

        np = NodePage(node_id=orphan_node.id, page_id=page.id)
        db.add(np)
        db.flush()

        with patch("app.routers.courses.delete_embeddings"):
            response = client.delete(f"/courses/{course.id}/documents/{doc.id}")

        assert response.status_code == 204

        # Orphan node should be auto-deleted
        assert db.query(Node).filter_by(id=orphan_node.id).first() is None

    def test_delete_document_keeps_multi_doc_nodes(self, client, db):
        course = Course(title="Multi Doc Course")
        db.add(course)
        db.flush()

        doc1 = Document(
            course_id=course.id, title="Doc 1", filename="d1.pdf",
            file_path="/tmp/d1.pdf", file_hash="multi001", upload_order=1,
            page_count=1, ingestion_status="complete",
        )
        doc2 = Document(
            course_id=course.id, title="Doc 2", filename="d2.pdf",
            file_path="/tmp/d2.pdf", file_hash="multi002", upload_order=2,
            page_count=1, ingestion_status="complete",
        )
        db.add_all([doc1, doc2])
        db.flush()

        page1 = Page(
            document_id=doc1.id, course_id=course.id,
            page_number=1, global_page=1,
            slide_title="S1", body="Content 1",
        )
        page2 = Page(
            document_id=doc2.id, course_id=course.id,
            page_number=1, global_page=2,
            slide_title="S2", body="Content 2",
        )
        db.add_all([page1, page2])
        db.flush()

        # Node linked to pages from BOTH documents — should survive
        shared_node = Node(course_id=course.id, title="Shared Topic", depth=1, order_index=0)
        db.add(shared_node)
        db.flush()

        np1 = NodePage(node_id=shared_node.id, page_id=page1.id)
        np2 = NodePage(node_id=shared_node.id, page_id=page2.id)
        db.add_all([np1, np2])
        db.flush()

        with patch("app.routers.courses.delete_embeddings"):
            response = client.delete(f"/courses/{course.id}/documents/{doc1.id}")

        assert response.status_code == 204

        # Shared node should survive (still linked to page2)
        surviving = db.query(Node).filter_by(id=shared_node.id).first()
        assert surviving is not None

    def test_delete_document_not_found(self, client, db):
        course = Course(title="NF Course")
        db.add(course)
        db.flush()

        response = client.delete(f"/courses/{course.id}/documents/{uuid.uuid4()}")
        assert response.status_code == 404

    def test_delete_document_wrong_course(self, client, db):
        course1 = Course(title="Course A")
        course2 = Course(title="Course B")
        db.add_all([course1, course2])
        db.flush()

        doc = Document(
            course_id=course1.id, title="Doc", filename="d.pdf",
            file_path="/tmp/d.pdf", file_hash="wrongcourse001", upload_order=1,
        )
        db.add(doc)
        db.flush()

        response = client.delete(f"/courses/{course2.id}/documents/{doc.id}")
        assert response.status_code == 404


class TestDeleteCourseEndpoint:
    def test_delete_course_returns_204(self, client, db):
        course = Course(title="To Delete")
        db.add(course)
        db.flush()

        doc = Document(
            course_id=course.id, title="Lec", filename="l.pdf",
            file_path="/tmp/l.pdf", file_hash="delcourse001", upload_order=1,
            page_count=1, ingestion_status="complete",
        )
        db.add(doc)
        db.flush()

        page = Page(
            document_id=doc.id, course_id=course.id,
            page_number=1, global_page=1,
            slide_title="S1", body="Content",
        )
        db.add(page)
        db.flush()

        node = Node(course_id=course.id, title="Topic", depth=1, order_index=0)
        db.add(node)
        db.flush()

        np = NodePage(node_id=node.id, page_id=page.id)
        db.add(np)
        db.flush()

        with patch("app.routers.courses.delete_collection") as mock_del:
            response = client.delete(f"/courses/{course.id}")

        assert response.status_code == 204

        # Everything should be gone
        assert db.query(Course).filter_by(id=course.id).first() is None
        assert db.query(Document).filter_by(course_id=course.id).all() == []
        assert db.query(Node).filter_by(course_id=course.id).all() == []

        # Collection cleanup was called
        mock_del.assert_called_once_with(str(course.id))

    def test_delete_course_not_found(self, client):
        response = client.delete(f"/courses/{uuid.uuid4()}")
        assert response.status_code == 404


class TestCreateCourseEndpoint:
    def test_create_course_creates_misc_node(self, client, db):
        response = client.post("/courses", json={"title": "Test"})
        assert response.status_code == 201
        course_id = response.json()["id"]
        misc = db.query(Node).filter_by(course_id=uuid.UUID(course_id), title="Miscellaneous").first()
        assert misc is not None
        assert misc.node_type == "group"
        assert misc.depth == 1
        assert misc.order_index == 999
