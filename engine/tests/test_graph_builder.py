# engine/tests/test_graph_builder.py
import hashlib
import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.models.course import Course
from app.models.node import Node, NodeEdge
from app.models.sentence import Sentence, NodeSentence
from app.services.graph_builder import GraphBuilder


def _seed_course_with_sentences(db) -> tuple:
    """Create a course with 3 sentences across 2 pages."""
    course = Course(
        title="Test Course",
        source_pdf_path="/fake.pdf",
        source_pdf_hash=hashlib.sha256(b"test").hexdigest(),
        ingestion_status="complete",
    )
    db.add(course)
    db.flush()

    sentences = []
    for page, pos, title, text in [
        (1, 0, "Intro", "Machine learning is a subset of AI."),
        (1, 1, "Intro", "It learns from data."),
        (2, 0, "Regression", "Linear regression fits a line."),
    ]:
        s = Sentence(
            course_id=course.id,
            page=page,
            position=pos,
            slide_title=title,
            text=text,
            hash=hashlib.sha256(text.encode()).hexdigest(),
        )
        sentences.append(s)
    db.add_all(sentences)
    db.flush()

    return course, sentences


MOCK_TOPICS_RESPONSE = {
    "topics": [
        {
            "title": "Machine Learning Fundamentals",
            "description": "Core ML concepts and paradigms.",
            "depth": 1,
            "parent_title": None,
            "source_chunk_indices": [0],
            "keywords": ["machine learning", "AI", "data"],
        },
        {
            "title": "Linear Regression Methods",
            "description": "Fitting linear models to data.",
            "depth": 2,
            "parent_title": "Machine Learning Fundamentals",
            "source_chunk_indices": [1],
            "keywords": ["regression", "linear", "fitting"],
        },
    ]
}

MOCK_EDGES_RESPONSE = {
    "edges": [
        {
            "from_title": "Machine Learning Fundamentals",
            "to_title": "Linear Regression Methods",
            "edge_type": "prerequisite",
            "reasoning": "ML fundamentals must be understood before learning regression techniques.",
        }
    ]
}


class TestGraphBuilder:
    @patch("app.services.graph_builder.LLMClient")
    def test_happy_path_creates_nodes_edges_and_mappings(self, mock_llm_class, db):
        course, sentences = _seed_course_with_sentences(db)

        mock_llm = MagicMock()
        mock_llm.extract_topics.return_value = MOCK_TOPICS_RESPONSE
        mock_llm.infer_dependencies.return_value = MOCK_EDGES_RESPONSE
        mock_llm_class.return_value = mock_llm

        builder = GraphBuilder(db=db, openai_api_key="fake")
        result = builder.run(course_id=course.id, max_depth=3)

        # Check result summary
        assert result["nodes_created"] == 2
        assert result["edges_created"] == 1
        assert result["node_sentences_created"] > 0

        # Check nodes in DB
        nodes = db.query(Node).filter_by(course_id=course.id).all()
        assert len(nodes) == 2
        titles = {n.title for n in nodes}
        assert "Machine Learning Fundamentals" in titles
        assert "Linear Regression Methods" in titles

        # Check depths
        root = next(n for n in nodes if n.title == "Machine Learning Fundamentals")
        child = next(n for n in nodes if n.title == "Linear Regression Methods")
        assert root.depth == 1
        assert child.depth == 2

        # Check edges
        edges = db.query(NodeEdge).all()
        assert len(edges) == 1
        assert edges[0].parent_id == root.id
        assert edges[0].child_id == child.id
        assert edges[0].edge_type == "prerequisite"

        # Check denormalized arrays
        db.refresh(root)
        db.refresh(child)
        assert child.id in root.child_ids
        assert root.id in child.parent_ids

        # Check node_sentences
        ns_rows = db.query(NodeSentence).all()
        assert len(ns_rows) > 0

        # Check content_chunk_ids populated
        assert len(root.content_chunk_ids) > 0
        assert len(child.content_chunk_ids) > 0

        # Check course status
        db.refresh(course)
        assert course.ingestion_status == "graph_ready"

    @patch("app.services.graph_builder.LLMClient")
    def test_rerun_wipes_old_nodes(self, mock_llm_class, db):
        course, sentences = _seed_course_with_sentences(db)

        mock_llm = MagicMock()
        mock_llm.extract_topics.return_value = MOCK_TOPICS_RESPONSE
        mock_llm.infer_dependencies.return_value = MOCK_EDGES_RESPONSE
        mock_llm_class.return_value = mock_llm

        builder = GraphBuilder(db=db, openai_api_key="fake")

        # First run
        builder.run(course_id=course.id, max_depth=3)
        first_node_ids = {n.id for n in db.query(Node).filter_by(course_id=course.id).all()}

        # Second run (re-run)
        builder.run(course_id=course.id, max_depth=3)
        second_node_ids = {n.id for n in db.query(Node).filter_by(course_id=course.id).all()}

        # Old nodes should be gone, new ones created
        assert first_node_ids.isdisjoint(second_node_ids)
        assert len(second_node_ids) == 2
