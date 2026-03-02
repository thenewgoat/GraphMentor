import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db.postgres import get_db
from app.models.course import Course
from app.models.node import Node, NodeEdge
from app.models.sentence import Sentence, NodeSentence


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
        course = Course(
            title="Test Course",
            source_pdf_path="/tmp/test.pdf",
            source_pdf_hash="abc123",
        )
        db.add(course)
        db.flush()

        response = client.get("/courses")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["title"] == "Test Course"
        assert data[0]["ingestion_status"] == "pending"

    def test_get_course_found(self, client, db):
        course = Course(
            title="Test Course",
            source_pdf_path="/tmp/test.pdf",
            source_pdf_hash="def456",
        )
        db.add(course)
        db.flush()

        response = client.get(f"/courses/{course.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "Test Course"
        assert "id" in data

    def test_get_course_not_found(self, client):
        response = client.get(f"/courses/{uuid.uuid4()}")
        assert response.status_code == 404


class TestGraphEndpoint:
    def test_get_graph_empty(self, client, db):
        course = Course(
            title="Empty Course",
            source_pdf_path="/tmp/test.pdf",
            source_pdf_hash="graph_empty_001",
            ingestion_status="graph_ready",
        )
        db.add(course)
        db.flush()

        response = client.get(f"/courses/{course.id}/graph")
        assert response.status_code == 200
        data = response.json()
        assert data["nodes"] == []
        assert data["edges"] == []

    def test_get_graph_with_data(self, client, db):
        course = Course(
            title="Graph Course",
            source_pdf_path="/tmp/test.pdf",
            source_pdf_hash="graph_data_001",
            ingestion_status="graph_ready",
        )
        db.add(course)
        db.flush()

        node_a = Node(course_id=course.id, title="Intro", depth=0, order_index=0)
        node_b = Node(course_id=course.id, title="Basics", depth=1, order_index=1)
        db.add_all([node_a, node_b])
        db.flush()

        edge = NodeEdge(parent_id=node_a.id, child_id=node_b.id, edge_type="prerequisite")
        db.add(edge)

        sentence = Sentence(
            course_id=course.id, page=1, position=0,
            slide_title="Slide 1", text="Hello world", hash="s001",
        )
        db.add(sentence)
        db.flush()

        ns = NodeSentence(node_id=node_a.id, sentence_id=sentence.id)
        db.add(ns)
        db.flush()

        response = client.get(f"/courses/{course.id}/graph")
        assert response.status_code == 200
        data = response.json()
        assert len(data["nodes"]) == 2
        assert len(data["edges"]) == 1
        assert data["edges"][0]["edge_type"] == "prerequisite"
        # Check sentences are included in node
        intro_node = next(n for n in data["nodes"] if n["title"] == "Intro")
        assert len(intro_node["sentences"]) == 1
        assert intro_node["sentences"][0]["text"] == "Hello world"

    def test_get_graph_course_not_found(self, client):
        response = client.get(f"/courses/{uuid.uuid4()}/graph")
        assert response.status_code == 404
