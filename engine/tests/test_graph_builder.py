"""Tests for fresh graph creation and multi-document merge with mocked LLM."""
import hashlib
import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.models.course import Course
from app.models.node import Node, NodeEdge
from app.models.document import Document, Page, NodePage
from app.services.graph_builder import GraphBuilder


def _seed_course_with_pages(db) -> tuple:
    """Create a course with a document and 2 pages."""
    course = Course(title="Test Course", ingestion_status="complete")
    db.add(course)
    db.flush()

    doc = Document(
        course_id=course.id, title="Lecture 1", filename="lec1.pdf",
        file_path="/tmp/lec1.pdf", file_hash=hashlib.sha256(b"test").hexdigest(),
        upload_order=1, page_count=2, ingestion_status="complete",
    )
    db.add(doc)
    db.flush()

    pages = []
    for page_num, title, body in [
        (1, "Intro", "Machine learning is a subset of AI. It learns from data."),
        (2, "Regression", "Linear regression fits a line to data."),
    ]:
        p = Page(
            document_id=doc.id, course_id=course.id,
            page_number=page_num, global_page=page_num,
            slide_title=title, body=body,
        )
        pages.append(p)
    db.add_all(pages)
    db.flush()

    return course, doc, pages


MOCK_TOPICS_RESPONSE = {
    "topics": [
        {
            "title": "Machine Learning Fundamentals",
            "description": "Core ML concepts and paradigms.",
            "depth": 1,
            "parent_title": None,
            "source_page_indices": [0],
            "keywords": ["machine learning", "AI", "data"],
        },
        {
            "title": "Linear Regression Methods",
            "description": "Fitting linear models to data.",
            "depth": 2,
            "parent_title": "Machine Learning Fundamentals",
            "source_page_indices": [1],
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
    def test_happy_path_creates_nodes_edges_and_page_links(self, mock_llm_class, db):
        course, doc, pages = _seed_course_with_pages(db)

        mock_llm = MagicMock()
        mock_llm.extract_topics.return_value = MOCK_TOPICS_RESPONSE
        mock_llm.infer_dependencies.return_value = MOCK_EDGES_RESPONSE
        mock_llm.extract_references.return_value = {"references": []}
        mock_llm_class.return_value = mock_llm

        builder = GraphBuilder(db=db, openai_api_key="fake")
        result = builder.run(course_id=course.id, document_id=doc.id, max_depth=3)

        # Check result summary
        assert result["nodes_created"] == 2
        assert result["edges_created"] == 1
        assert result["nodes_extended"] == 0

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

        # Check denormalized arrays
        db.refresh(root)
        db.refresh(child)
        assert child.id in root.child_ids
        assert root.id in child.parent_ids

        # Check node_pages
        np_rows = db.query(NodePage).all()
        assert len(np_rows) > 0

        # Check course status
        db.refresh(course)
        assert course.ingestion_status == "graph_ready"

    @patch("app.services.graph_builder.LLMClient")
    def test_merge_extends_existing_nodes(self, mock_llm_class, db):
        """Second document should merge into existing graph."""
        course, doc1, pages1 = _seed_course_with_pages(db)

        mock_llm = MagicMock()
        mock_llm.extract_topics.return_value = MOCK_TOPICS_RESPONSE
        mock_llm.infer_dependencies.return_value = MOCK_EDGES_RESPONSE
        mock_llm.extract_references.return_value = {"references": []}
        mock_llm_class.return_value = mock_llm

        builder = GraphBuilder(db=db, openai_api_key="fake")

        # First document: creates fresh graph
        builder.run(course_id=course.id, document_id=doc1.id, max_depth=3)
        first_nodes = db.query(Node).filter_by(course_id=course.id).all()
        assert len(first_nodes) == 2

        # Create second document
        doc2 = Document(
            course_id=course.id, title="Lecture 2", filename="lec2.pdf",
            file_path="/tmp/lec2.pdf", file_hash="b" * 64,
            upload_order=2, page_count=1, ingestion_status="complete",
        )
        db.add(doc2)
        db.flush()
        page2 = Page(
            document_id=doc2.id, course_id=course.id,
            page_number=1, global_page=3,
            slide_title="Advanced ML", body="Neural networks are powerful.",
        )
        db.add(page2)
        db.flush()

        # Mock merge response
        mock_llm.extract_topics.return_value = {
            "topics": [{
                "title": "Neural Networks",
                "description": "Deep learning basics.",
                "depth": 1,
                "parent_title": None,
                "source_page_indices": [0],
                "keywords": ["neural", "network", "deep learning"],
            }]
        }
        mock_llm.merge_topics.return_value = {
            "decisions": [{
                "new_title": "Neural Networks",
                "action": "NEW",
                "depth": 2,
                "source_page_indices": [0],
                "reasoning": "New concept not in existing graph.",
            }]
        }

        result = builder.run(course_id=course.id, document_id=doc2.id, max_depth=3)
        assert result["nodes_created"] == 1
        assert result["nodes_extended"] == 0

        all_nodes = db.query(Node).filter_by(course_id=course.id).all()
        assert len(all_nodes) == 3
