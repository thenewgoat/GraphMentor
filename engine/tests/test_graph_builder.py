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
            "node_type": "group",
            "parent_title": None,
            "source_page_indices": [0],
            "keywords": ["machine learning", "AI", "data"],
        },
        {
            "title": "Linear Regression Methods",
            "description": "Fitting linear models to data.",
            "depth": 2,
            "node_type": "concept",
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
            "edge_category": "dependency",
            "edge_label": "is prerequisite for",
            "reasoning": "ML fundamentals must be understood before learning regression techniques.",
        }
    ]
}


class TestGraphBuilder:
    @patch("app.services.graph_builder.get_or_create_collection")
    @patch("app.services.graph_builder.delete_collection")
    @patch("app.services.graph_builder.EmbeddingValidator")
    @patch("app.services.graph_builder.ConnectivityValidator")
    @patch("app.services.graph_builder.LLMClient")
    def test_happy_path_creates_nodes_edges_and_page_links(self, mock_llm_class, mock_conn_cls, mock_embed_cls, mock_del_coll, mock_get_coll, db):
        course, doc, pages = _seed_course_with_pages(db)

        mock_llm = MagicMock()
        mock_llm.extract_topics.return_value = MOCK_TOPICS_RESPONSE
        mock_llm.infer_dependencies.return_value = MOCK_EDGES_RESPONSE
        mock_llm.extract_references.return_value = {"references": []}
        mock_llm_class.return_value = mock_llm

        # EmbeddingValidator.validate passes through topics unchanged
        mock_embed_cls.return_value.validate.side_effect = lambda topics, **kw: topics
        # ConnectivityValidator.validate passes through edges unchanged
        mock_conn_cls.return_value.validate.side_effect = lambda topics, edges: edges
        mock_get_coll.return_value = MagicMock()

        builder = GraphBuilder(db=db, openai_api_key="fake")
        result = builder.run(course_id=course.id, document_id=doc.id, max_depth=7)

        # Check result summary
        assert result["nodes_created"] == 3
        assert result["edges_created"] >= 1
        assert result["nodes_extended"] == 0

        # Check nodes in DB
        nodes = db.query(Node).filter_by(course_id=course.id).all()
        assert len(nodes) == 3
        titles = {n.title for n in nodes}
        assert "Machine Learning Fundamentals" in titles
        assert "Linear Regression Methods" in titles
        assert "Test Course" in titles  # root = course title

        # Check depths
        group_node = next(n for n in nodes if n.title == "Machine Learning Fundamentals")
        child = next(n for n in nodes if n.title == "Linear Regression Methods")
        assert group_node.depth == 1
        assert child.depth == 2

        # Check edges (dependency + hierarchy from root to depth-1)
        edges = db.query(NodeEdge).all()
        assert len(edges) >= 1
        dep_edge = next(e for e in edges if e.edge_category == "dependency")
        assert dep_edge.parent_id == group_node.id
        assert dep_edge.child_id == child.id

        # Check root node = course title
        root = db.query(Node).filter_by(course_id=course.id, depth=0).first()
        assert root is not None
        assert root.title == "Test Course"
        assert root.node_type == "group"

        # Check denormalized arrays
        db.refresh(group_node)
        db.refresh(child)
        assert child.id in group_node.child_ids
        assert group_node.id in child.parent_ids

        # Check node_pages
        np_rows = db.query(NodePage).all()
        assert len(np_rows) > 0

        # Check course status
        db.refresh(course)
        assert course.ingestion_status == "graph_ready"

    @patch("app.services.graph_builder.get_or_create_collection")
    @patch("app.services.graph_builder.delete_collection")
    @patch("app.services.graph_builder.EmbeddingValidator")
    @patch("app.services.graph_builder.ConnectivityValidator")
    @patch("app.services.graph_builder.LLMClient")
    def test_merge_extends_existing_nodes(self, mock_llm_class, mock_conn_cls, mock_embed_cls, mock_del_coll, mock_get_coll, db):
        """Second document should merge into existing graph."""
        course, doc1, pages1 = _seed_course_with_pages(db)

        mock_llm = MagicMock()
        mock_llm.extract_topics.return_value = MOCK_TOPICS_RESPONSE
        mock_llm.infer_dependencies.return_value = MOCK_EDGES_RESPONSE
        mock_llm.extract_references.return_value = {"references": []}
        mock_llm_class.return_value = mock_llm

        # EmbeddingValidator.validate passes through topics unchanged
        mock_embed_cls.return_value.validate.side_effect = lambda topics, **kw: topics
        # ConnectivityValidator.validate passes through edges unchanged
        mock_conn_cls.return_value.validate.side_effect = lambda topics, edges: edges
        mock_get_coll.return_value = MagicMock()

        builder = GraphBuilder(db=db, openai_api_key="fake")

        # First document: creates fresh graph
        builder.run(course_id=course.id, document_id=doc1.id, max_depth=7)
        first_nodes = db.query(Node).filter_by(course_id=course.id).all()
        assert len(first_nodes) == 3

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

        result = builder.run(course_id=course.id, document_id=doc2.id, max_depth=7)
        assert result["nodes_created"] == 1
        assert result["nodes_extended"] == 0

        all_nodes = db.query(Node).filter_by(course_id=course.id).all()
        assert len(all_nodes) == 4

    @patch("app.services.graph_builder.get_or_create_collection")
    @patch("app.services.graph_builder.delete_collection")
    @patch("app.services.graph_builder.EmbeddingValidator")
    @patch("app.services.graph_builder.ConnectivityValidator")
    @patch("app.services.graph_builder.LLMClient")
    def test_fresh_graph_creates_root_node_with_course_title(self, mock_llm_class, mock_conn_cls, mock_embed_cls, mock_del_coll, mock_get_coll, db):
        """First document should create a depth-0 root node with the course title."""
        course, doc, pages = _seed_course_with_pages(db)

        mock_llm = MagicMock()
        mock_llm.extract_topics.return_value = MOCK_TOPICS_RESPONSE
        mock_llm.infer_dependencies.return_value = MOCK_EDGES_RESPONSE
        mock_llm.extract_references.return_value = {"references": []}
        mock_llm_class.return_value = mock_llm

        # EmbeddingValidator.validate passes through topics unchanged
        mock_embed_cls.return_value.validate.side_effect = lambda topics, **kw: topics
        # ConnectivityValidator.validate passes through edges unchanged
        mock_conn_cls.return_value.validate.side_effect = lambda topics, edges: edges
        mock_get_coll.return_value = MagicMock()

        builder = GraphBuilder(db=db, openai_api_key="fake")
        result = builder.run(course_id=course.id, document_id=doc.id, max_depth=7)

        # Root node should exist at depth 0 with course title
        root = db.query(Node).filter_by(course_id=course.id, depth=0).first()
        assert root is not None
        assert root.title == "Test Course"
        assert root.node_type == "group"

        # Course should have topic_title = course title
        db.refresh(course)
        assert course.topic_title == "Test Course"

        # Hierarchy edges from root to all depth-1 nodes
        hierarchy_edges = (
            db.query(NodeEdge)
            .filter_by(parent_id=root.id, edge_category="hierarchy")
            .all()
        )
        depth1_nodes = db.query(Node).filter_by(course_id=course.id, depth=1).all()
        assert len(hierarchy_edges) == len(depth1_nodes)
        for edge in hierarchy_edges:
            assert edge.edge_label == "contains"

        # Result counts: root + 2 original = 3
        assert result["nodes_created"] == 3

    @patch("app.services.graph_builder.get_or_create_collection")
    @patch("app.services.graph_builder.delete_collection")
    @patch("app.services.graph_builder.EmbeddingValidator")
    @patch("app.services.graph_builder.ConnectivityValidator")
    @patch("app.services.graph_builder.LLMClient")
    def test_merge_connects_new_depth1_nodes_to_root(self, mock_llm_class, mock_conn_cls, mock_embed_cls, mock_del_coll, mock_get_coll, db):
        """New depth-1 nodes from second document should get hierarchy edge from root."""
        course, doc1, pages1 = _seed_course_with_pages(db)

        mock_llm = MagicMock()
        mock_llm.extract_topics.return_value = MOCK_TOPICS_RESPONSE
        mock_llm.infer_dependencies.return_value = MOCK_EDGES_RESPONSE
        mock_llm.extract_references.return_value = {"references": []}
        mock_llm_class.return_value = mock_llm

        # EmbeddingValidator.validate passes through topics unchanged
        mock_embed_cls.return_value.validate.side_effect = lambda topics, **kw: topics
        # ConnectivityValidator.validate passes through edges unchanged
        mock_conn_cls.return_value.validate.side_effect = lambda topics, edges: edges
        mock_get_coll.return_value = MagicMock()

        builder = GraphBuilder(db=db, openai_api_key="fake")
        builder.run(course_id=course.id, document_id=doc1.id, max_depth=7)

        # Create second document
        import hashlib
        doc2 = Document(
            course_id=course.id, title="Lecture 2", filename="lec2.pdf",
            file_path="/tmp/lec2.pdf", file_hash="c" * 64,
            upload_order=2, page_count=1, ingestion_status="complete",
        )
        db.add(doc2)
        db.flush()
        page2 = Page(
            document_id=doc2.id, course_id=course.id,
            page_number=1, global_page=3,
            slide_title="Deep Learning", body="Neural networks.",
        )
        db.add(page2)
        db.flush()

        mock_llm.extract_topics.return_value = {
            "topics": [{
                "title": "Deep Learning Methods",
                "description": "Neural network approaches.",
                "depth": 1,
                "node_type": "group",
                "parent_title": None,
                "source_page_indices": [0],
                "keywords": ["deep learning", "neural", "networks"],
            }]
        }
        mock_llm.merge_topics.return_value = {
            "decisions": [{
                "new_title": "Deep Learning Methods",
                "action": "NEW",
                "depth": 1,
                "node_type": "group",
                "source_page_indices": [0],
                "reasoning": "New group not in existing graph.",
            }]
        }

        builder.run(course_id=course.id, document_id=doc2.id, max_depth=7)

        # Root should have hierarchy edge to the new depth-1 group
        root = db.query(Node).filter_by(course_id=course.id, depth=0).first()
        new_group = db.query(Node).filter_by(course_id=course.id, title="Deep Learning Methods").first()
        assert root is not None
        assert new_group is not None

        edge = db.get(NodeEdge, (root.id, new_group.id))
        assert edge is not None
        assert edge.edge_category == "hierarchy"
        assert edge.edge_label == "contains"
