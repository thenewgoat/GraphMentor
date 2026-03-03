"""Tests for topic, merge, dependency, and embedding validators with cycle detection."""
import pytest
from unittest.mock import patch, MagicMock
import numpy as np

from app.services.validators import (
    TopicValidator,
    DependencyValidator,
    MergeValidator,
    EmbeddingValidator,
    ConnectivityValidator,
    ValidationError,
)


def _valid_topics():
    """Minimal valid topic extraction response."""
    return {
        "topics": [
            {
                "title": "Machine Learning Basics",
                "description": "Introduction to ML concepts.",
                "depth": 1,
                "parent_title": None,
                "source_page_indices": [0, 1],
                "keywords": ["machine learning", "supervised", "unsupervised"],
            },
            {
                "title": "Linear Regression",
                "description": "Fitting a line to data points.",
                "depth": 2,
                "parent_title": "Machine Learning Basics",
                "source_page_indices": [1],
                "keywords": ["regression", "linear", "least squares"],
            },
            {
                "title": "Decision Trees",
                "description": "Tree-based classification and regression.",
                "depth": 2,
                "parent_title": "Machine Learning Basics",
                "source_page_indices": [2],
                "keywords": ["decision tree", "split", "entropy"],
            },
        ]
    }


class TestTopicValidator:
    def test_valid_response_passes(self):
        validator = TopicValidator(num_pages=3, max_depth=3)
        result = validator.validate(_valid_topics())
        assert len(result["topics"]) == 3
        # depth-1 forced to group, depth-2 defaults to concept
        assert result["topics"][0]["node_type"] == "group"
        assert result["topics"][1]["node_type"] == "concept"
        assert result["topics"][2]["node_type"] == "concept"

    def test_duplicate_titles_rejected(self):
        data = _valid_topics()
        data["topics"][2]["title"] = "Linear Regression"
        validator = TopicValidator(num_pages=3, max_depth=3)
        with pytest.raises(ValidationError, match="[Dd]uplicate"):
            validator.validate(data)

    def test_invalid_parent_title_rejected(self):
        data = _valid_topics()
        data["topics"][1]["parent_title"] = "Nonexistent Topic"
        validator = TopicValidator(num_pages=3, max_depth=3)
        with pytest.raises(ValidationError, match="[Pp]arent"):
            validator.validate(data)

    def test_depth_exceeds_max_clamped(self):
        data = _valid_topics()
        data["topics"][1]["depth"] = 5
        validator = TopicValidator(num_pages=3, max_depth=3)
        result = validator.validate(data)
        clamped = next(t for t in result["topics"] if t["title"] == data["topics"][1]["title"])
        assert clamped["depth"] == 3

    def test_invalid_page_index_rejected(self):
        data = _valid_topics()
        data["topics"][0]["source_page_indices"] = [0, 99]
        validator = TopicValidator(num_pages=3, max_depth=3)
        with pytest.raises(ValidationError, match="[Pp]age"):
            validator.validate(data)

    def test_empty_page_indices_drops_concept(self):
        data = _valid_topics()
        data["topics"][1]["source_page_indices"] = []  # concept topic
        validator = TopicValidator(num_pages=3, max_depth=3)
        result = validator.validate(data)
        titles = [t["title"] for t in result["topics"]]
        assert "Linear Regression" not in titles

    def test_empty_page_indices_allowed_for_groups(self):
        data = _valid_topics()
        data["topics"][0]["node_type"] = "group"
        data["topics"][0]["source_page_indices"] = []
        validator = TopicValidator(num_pages=3, max_depth=3)
        result = validator.validate(data)
        assert result["topics"][0]["source_page_indices"] == []

    def test_same_depth_parent_child_auto_corrected(self):
        data = _valid_topics()
        # Set child "Linear Regression" to same depth as parent "Machine Learning Basics"
        data["topics"][1]["depth"] = 1
        validator = TopicValidator(num_pages=3, max_depth=3)
        result = validator.validate(data)
        # Should auto-correct to parent_depth + 1 = 2, not raise
        lr = next(t for t in result["topics"] if t["title"] == "Linear Regression")
        assert lr["depth"] == 2

    def test_node_type_passed_through(self):
        data = _valid_topics()
        data["topics"][0]["node_type"] = "group"
        data["topics"][1]["node_type"] = "concept"
        data["topics"][2]["node_type"] = "concept"
        validator = TopicValidator(num_pages=3, max_depth=3)
        result = validator.validate(data)
        assert result["topics"][0]["node_type"] == "group"

    def test_node_type_defaults_to_concept(self):
        data = _valid_topics()
        # No node_type field at all — depth-1 forced to group, depth-2 defaults to concept
        validator = TopicValidator(num_pages=3, max_depth=3)
        result = validator.validate(data)
        assert result["topics"][0]["node_type"] == "group"   # depth 1 → group
        assert result["topics"][1]["node_type"] == "concept"  # depth 2
        assert result["topics"][2]["node_type"] == "concept"  # depth 2

    def test_invalid_node_type_defaults_to_concept(self):
        data = _valid_topics()
        data["topics"][0]["node_type"] = "invalid"
        validator = TopicValidator(num_pages=3, max_depth=3)
        result = validator.validate(data)
        # depth-1 topic: invalid → concept → forced to group
        assert result["topics"][0]["node_type"] == "group"


class TestMergeValidator:
    def test_valid_merge_decisions_pass(self):
        data = {
            "decisions": [
                {"new_title": "X", "action": "NEW", "source_page_indices": [0], "reasoning": "new"},
                {"new_title": "Y", "action": "EXTEND", "existing_node_title": "A", "source_page_indices": [1], "reasoning": "overlap"},
                {"new_title": "Z", "action": "SKIP", "reasoning": "covered"},
            ]
        }
        validator = MergeValidator(existing_titles={"A", "B"}, num_new_pages=3)
        result = validator.validate(data)
        assert len(result["decisions"]) == 3

    def test_extend_unknown_node_converted_to_new(self):
        data = {
            "decisions": [
                {"new_title": "X", "action": "EXTEND", "existing_node_title": "Nonexistent", "reasoning": "bad ref"},
            ]
        }
        validator = MergeValidator(existing_titles={"A"}, num_new_pages=2)
        result = validator.validate(data)
        assert result["decisions"][0]["action"] == "NEW"

    def test_unknown_action_skipped(self):
        data = {
            "decisions": [
                {"new_title": "X", "action": "UNKNOWN", "reasoning": "?"},
                {"new_title": "Y", "action": "NEW", "reasoning": "ok"},
            ]
        }
        validator = MergeValidator(existing_titles=set(), num_new_pages=2)
        result = validator.validate(data)
        assert len(result["decisions"]) == 1

    def test_missing_decisions_raises(self):
        validator = MergeValidator(existing_titles=set(), num_new_pages=1)
        with pytest.raises(ValidationError, match="decisions"):
            validator.validate({"topics": []})


def _topics_for_deps():
    """Topic list for dependency validation tests."""
    return [
        {"title": "Basics", "depth": 1},
        {"title": "Intermediate", "depth": 2},
        {"title": "Advanced", "depth": 2},
        {"title": "Expert", "depth": 2},
        {"title": "Final", "depth": 2},
    ]


def _valid_edges():
    return {
        "edges": [
            {"from_title": "Basics", "to_title": "Intermediate", "edge_category": "dependency", "edge_label": "builds upon", "reasoning": "Basics provides foundation for Intermediate concepts."},
            {"from_title": "Intermediate", "to_title": "Advanced", "edge_category": "dependency", "edge_label": "prerequisite for", "reasoning": "Intermediate builds toward Advanced material."},
        ]
    }


class TestDependencyValidator:
    def test_valid_edges_pass(self):
        validator = DependencyValidator(topics=_topics_for_deps())
        result = validator.validate(_valid_edges())
        assert len(result["edges"]) == 2

    def test_unknown_title_removed(self):
        data = _valid_edges()
        data["edges"].append(
            {"from_title": "Ghost", "to_title": "Intermediate", "edge_category": "dependency", "edge_label": "builds upon", "reasoning": "Invalid."}
        )
        validator = DependencyValidator(topics=_topics_for_deps())
        result = validator.validate(data)
        assert len(result["edges"]) == 2

    def test_cycle_detected_and_broken(self):
        data = {
            "edges": [
                {"from_title": "Intermediate", "to_title": "Advanced", "edge_category": "dependency", "edge_label": "leads to", "reasoning": "Intermediate leads to Advanced material."},
                {"from_title": "Advanced", "to_title": "Intermediate", "edge_category": "dependency", "edge_label": "leads to", "reasoning": "Cycle."},
            ]
        }
        validator = DependencyValidator(topics=_topics_for_deps())
        result = validator.validate(data)
        assert len(result["edges"]) == 1
        assert result["edges"][0]["reasoning"] == "Intermediate leads to Advanced material."

    def test_root_topic_protection(self):
        data = {
            "edges": [
                {"from_title": "Intermediate", "to_title": "Basics", "edge_category": "dependency", "edge_label": "depends on", "reasoning": "Should be removed."},
            ]
        }
        validator = DependencyValidator(topics=_topics_for_deps())
        result = validator.validate(data)
        assert len(result["edges"]) == 0

    def test_edge_categories_pass(self):
        data = {
            "edges": [
                {"from_title": "Basics", "to_title": "Intermediate", "edge_category": "hierarchy", "edge_label": "contains", "reasoning": "Hierarchy relationship."},
                {"from_title": "Basics", "to_title": "Advanced", "edge_category": "association", "edge_label": "related to", "reasoning": "Associated concepts."},
                {"from_title": "Advanced", "to_title": "Final", "edge_category": "dependency", "edge_label": "motivates", "reasoning": "Motivates Final topic."},
            ]
        }
        validator = DependencyValidator(topics=_topics_for_deps())
        result = validator.validate(data)
        assert len(result["edges"]) == 3

    def test_max_three_dependencies_enforced(self):
        data = {
            "edges": [
                {"from_title": "Basics", "to_title": "Final", "edge_category": "dependency", "edge_label": "builds upon", "reasoning": "First reason is important."},
                {"from_title": "Intermediate", "to_title": "Final", "edge_category": "dependency", "edge_label": "leads to", "reasoning": "Second reason is also very important."},
                {"from_title": "Advanced", "to_title": "Final", "edge_category": "dependency", "edge_label": "required for", "reasoning": "Third reason is quite important too."},
                {"from_title": "Expert", "to_title": "Final", "edge_category": "dependency", "edge_label": "needed by", "reasoning": "Short."},
            ]
        }
        validator = DependencyValidator(topics=_topics_for_deps())
        result = validator.validate(data)
        deps_to_final = [e for e in result["edges"] if e["to_title"] == "Final" and e["edge_category"] == "dependency"]
        assert len(deps_to_final) == 3
        assert all(e["reasoning"] != "Short." for e in deps_to_final)

    def test_edge_label_truncated_to_100_chars(self):
        data = {
            "edges": [
                {"from_title": "Basics", "to_title": "Intermediate", "edge_category": "dependency", "edge_label": "x" * 150, "reasoning": "Long label."},
            ]
        }
        validator = DependencyValidator(topics=_topics_for_deps())
        result = validator.validate(data)
        assert len(result["edges"][0]["edge_label"]) == 100

    def test_invalid_edge_category_removed(self):
        data = {
            "edges": [
                {"from_title": "Basics", "to_title": "Intermediate", "edge_category": "invalid", "edge_label": "bad", "reasoning": "Bad category."},
                {"from_title": "Basics", "to_title": "Advanced", "edge_category": "dependency", "edge_label": "builds upon", "reasoning": "Good."},
            ]
        }
        validator = DependencyValidator(topics=_topics_for_deps())
        result = validator.validate(data)
        assert len(result["edges"]) == 1

    def test_empty_edge_label_defaults(self):
        data = {
            "edges": [
                {"from_title": "Basics", "to_title": "Intermediate", "edge_category": "dependency", "edge_label": "", "reasoning": "Empty label."},
            ]
        }
        validator = DependencyValidator(topics=_topics_for_deps())
        result = validator.validate(data)
        assert result["edges"][0]["edge_label"] == "related"

    def test_hierarchy_edges_from_depth0_root_preserved(self):
        """Root at depth 0 should be allowed to have hierarchy edges to depth-1 nodes."""
        topics = [
            {"title": "Root Topic", "depth": 0},
            {"title": "Group A", "depth": 1},
            {"title": "Concept B", "depth": 2},
        ]
        edges = {
            "edges": [
                {"from_title": "Root Topic", "to_title": "Group A",
                 "edge_category": "hierarchy", "edge_label": "contains",
                 "reasoning": "Root contains group."},
                {"from_title": "Group A", "to_title": "Concept B",
                 "edge_category": "dependency", "edge_label": "is prerequisite for",
                 "reasoning": "Group A prereq for B."},
            ]
        }
        validator = DependencyValidator(topics=topics)
        result = validator.validate(edges)
        titles = [(e["from_title"], e["to_title"]) for e in result["edges"]]
        assert ("Root Topic", "Group A") in titles

    def test_dependency_edges_to_depth0_root_blocked(self):
        """Dependency edges targeting the depth-0 root should be removed."""
        topics = [
            {"title": "Root", "depth": 0},
            {"title": "Group A", "depth": 1},
            {"title": "Concept B", "depth": 2},
        ]
        edges = {
            "edges": [
                {"from_title": "Concept B", "to_title": "Root",
                 "edge_category": "dependency", "edge_label": "depends on",
                 "reasoning": "Bad edge."},
                {"from_title": "Group A", "to_title": "Concept B",
                 "edge_category": "dependency", "edge_label": "prereq",
                 "reasoning": "Good edge."},
            ]
        }
        validator = DependencyValidator(topics=topics)
        result = validator.validate(edges)
        targets = [e["to_title"] for e in result["edges"]]
        assert "Root" not in targets
        assert "Concept B" in targets


# ---------------------------------------------------------------------------
# EmbeddingValidator tests
# ---------------------------------------------------------------------------

def _embedding_topics():
    """Two topics with controllable similarity for embedding tests."""
    return [
        {
            "title": "Neural Networks",
            "description": "Deep learning fundamentals.",
            "depth": 2,
            "parent_title": "ML Basics",
            "source_page_indices": [0, 1],
            "keywords": ["neural", "network", "deep"],
        },
        {
            "title": "Deep Neural Nets",
            "description": "Deep learning fundamentals.",
            "depth": 2,
            "parent_title": "ML Basics",
            "source_page_indices": [2, 3],
            "keywords": ["neural", "network", "deep"],
        },
        {
            "title": "Decision Trees",
            "description": "Tree-based classification and regression.",
            "depth": 2,
            "parent_title": "ML Basics",
            "source_page_indices": [4],
            "keywords": ["decision", "tree", "entropy"],
        },
    ]


def _make_near_identical_embeddings():
    """Return 3 embeddings: first two nearly identical, third orthogonal."""
    v1 = np.array([1.0, 0.0, 0.0])
    v2 = np.array([0.99, 0.1, 0.0])
    v2 = v2 / np.linalg.norm(v2)  # normalise
    v3 = np.array([0.0, 0.0, 1.0])
    return [v1.tolist(), v2.tolist(), v3.tolist()]


def _make_orthogonal_embeddings():
    """Return 3 mutually orthogonal unit vectors."""
    return [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]


class TestEmbeddingValidator:
    """Tests for EmbeddingValidator — mocks OpenAIEmbedder and ChromaDB."""

    @patch("app.services.validators.upsert_node_embeddings")
    @patch("app.services.validators.query_similar")
    @patch("app.services.validators.OpenAIEmbedder")
    def test_merges_similar_topics(self, MockEmbedder, mock_query, mock_upsert):
        """Two topics with near-identical embeddings get merged, page indices combined."""
        embedder_instance = MagicMock()
        embedder_instance.get_embeddings.return_value = _make_near_identical_embeddings()
        MockEmbedder.return_value = embedder_instance

        topics = _embedding_topics()
        validator = EmbeddingValidator(api_key="fake", course_id="c1", threshold=0.85)
        result = validator.validate(topics)

        # Topics 0 and 1 should merge (keeper = index 0), topic 2 survives
        assert len(result) == 2
        titles = [t["title"] for t in result]
        assert "Neural Networks" in titles
        assert "Deep Neural Nets" not in titles
        assert "Decision Trees" in titles

        # Page indices combined (union, sorted)
        nn = next(t for t in result if t["title"] == "Neural Networks")
        assert nn["source_page_indices"] == [0, 1, 2, 3]

    @patch("app.services.validators.upsert_node_embeddings")
    @patch("app.services.validators.query_similar")
    @patch("app.services.validators.OpenAIEmbedder")
    def test_no_merge_below_threshold(self, MockEmbedder, mock_query, mock_upsert):
        """Orthogonal embeddings produce no merges."""
        embedder_instance = MagicMock()
        embedder_instance.get_embeddings.return_value = _make_orthogonal_embeddings()
        MockEmbedder.return_value = embedder_instance

        topics = _embedding_topics()
        validator = EmbeddingValidator(api_key="fake", course_id="c1", threshold=0.85)
        result = validator.validate(topics)

        assert len(result) == 3

    @patch("app.services.validators.upsert_node_embeddings")
    @patch("app.services.validators.query_similar")
    @patch("app.services.validators.OpenAIEmbedder")
    def test_reparents_children_of_merged_topic(self, MockEmbedder, mock_query, mock_upsert):
        """Children of the dropped topic get reparented to the keeper."""
        embedder_instance = MagicMock()
        # First two embeddings nearly identical so topic 1 gets merged into topic 0
        embedder_instance.get_embeddings.return_value = _make_near_identical_embeddings()
        MockEmbedder.return_value = embedder_instance

        topics = _embedding_topics()
        # Make "Decision Trees" a child of the topic that will be dropped
        topics[2]["parent_title"] = "Deep Neural Nets"

        validator = EmbeddingValidator(api_key="fake", course_id="c1", threshold=0.85)
        result = validator.validate(topics)

        dt = next(t for t in result if t["title"] == "Decision Trees")
        # Should now point to the keeper "Neural Networks"
        assert dt["parent_title"] == "Neural Networks"

    @patch("app.services.validators.upsert_node_embeddings")
    @patch("app.services.validators.query_similar")
    @patch("app.services.validators.OpenAIEmbedder")
    def test_persists_embeddings_to_chromadb(self, MockEmbedder, mock_query, mock_upsert):
        """upsert_node_embeddings is called with correct args after validation."""
        embeddings = _make_orthogonal_embeddings()
        embedder_instance = MagicMock()
        embedder_instance.get_embeddings.return_value = embeddings
        MockEmbedder.return_value = embedder_instance

        topics = _embedding_topics()
        validator = EmbeddingValidator(api_key="fake", course_id="c1")
        validator.validate(topics)

        mock_upsert.assert_called_once()
        call_args = mock_upsert.call_args
        # course_id is passed as positional arg; rest are keyword args
        assert call_args[0][0] == "c1"
        assert call_args[1]["node_ids"] == [
            "Neural Networks",
            "Deep Neural Nets",
            "Decision Trees",
        ]
        assert call_args[1]["embeddings"] == embeddings
        assert len(call_args[1]["metadatas"]) == 3

    @patch("app.services.validators.upsert_node_embeddings")
    @patch("app.services.validators.query_similar")
    @patch("app.services.validators.OpenAIEmbedder")
    def test_multi_doc_dedup_against_existing(self, MockEmbedder, mock_query, mock_upsert):
        """New topic matching existing node in ChromaDB gets dropped."""
        embeddings = _make_orthogonal_embeddings()
        embedder_instance = MagicMock()
        embedder_instance.get_embeddings.return_value = embeddings
        MockEmbedder.return_value = embedder_instance

        # Simulate ChromaDB returning a very close match for the first topic
        # L2 distance of 0.0 → cosine_sim = 1.0 - (0.0 / 2.0) = 1.0
        mock_query.return_value = {
            "ids": [["Neural Networks"], ["no_match"], ["no_match"]],
            "distances": [[0.0], [2.0], [2.0]],
            "metadatas": [[{"title": "Neural Networks"}], [{}], [{}]],
            "documents": [[], [], []],
        }

        topics = _embedding_topics()
        existing_titles = {"Neural Networks"}
        validator = EmbeddingValidator(api_key="fake", course_id="c1", threshold=0.85)
        result = validator.validate(topics, existing_node_titles=existing_titles)

        titles = [t["title"] for t in result]
        assert "Neural Networks" not in titles
        assert "Deep Neural Nets" in titles
        assert "Decision Trees" in titles


# ---------------------------------------------------------------------------
# ConnectivityValidator tests
# ---------------------------------------------------------------------------

def _connectivity_topics():
    """Topics for connectivity validator tests: root, group, and concepts."""
    return [
        {"title": "Root", "depth": 0, "parent_title": None},
        {"title": "Group A", "depth": 1, "parent_title": "Root"},
        {"title": "Group B", "depth": 1, "parent_title": "Root"},
        {"title": "Concept X", "depth": 2, "parent_title": "Group A"},
        {"title": "Concept Y", "depth": 2, "parent_title": "Group A"},
        {"title": "Concept Z", "depth": 2, "parent_title": "Group B"},
    ]


class TestConnectivityValidator:
    def test_connected_topics_pass_unchanged(self):
        """All topics have edges — no new edges added."""
        topics = _connectivity_topics()
        edges = [
            {"from_title": "Root", "to_title": "Group A", "edge_category": "hierarchy", "edge_label": "contains", "reasoning": "r"},
            {"from_title": "Root", "to_title": "Group B", "edge_category": "hierarchy", "edge_label": "contains", "reasoning": "r"},
            {"from_title": "Group A", "to_title": "Concept X", "edge_category": "hierarchy", "edge_label": "contains", "reasoning": "r"},
            {"from_title": "Group A", "to_title": "Concept Y", "edge_category": "hierarchy", "edge_label": "contains", "reasoning": "r"},
            {"from_title": "Group B", "to_title": "Concept Z", "edge_category": "hierarchy", "edge_label": "contains", "reasoning": "r"},
        ]
        validator = ConnectivityValidator(root_title="Root")
        result = validator.validate(topics, edges)
        assert len(result) == 5  # unchanged

    def test_orphan_with_parent_title_auto_connected(self):
        """Orphan with parent_title gets hierarchy edge from parent."""
        topics = _connectivity_topics()
        # Edges cover all except Concept Y (orphan with parent_title="Group A")
        edges = [
            {"from_title": "Root", "to_title": "Group A", "edge_category": "hierarchy", "edge_label": "contains", "reasoning": "r"},
            {"from_title": "Root", "to_title": "Group B", "edge_category": "hierarchy", "edge_label": "contains", "reasoning": "r"},
            {"from_title": "Group A", "to_title": "Concept X", "edge_category": "hierarchy", "edge_label": "contains", "reasoning": "r"},
            {"from_title": "Group B", "to_title": "Concept Z", "edge_category": "hierarchy", "edge_label": "contains", "reasoning": "r"},
        ]
        validator = ConnectivityValidator(root_title="Root")
        result = validator.validate(topics, edges)
        assert len(result) == 5  # 4 original + 1 auto-generated
        auto = result[-1]
        assert auto["from_title"] == "Group A"
        assert auto["to_title"] == "Concept Y"
        assert auto["edge_category"] == "hierarchy"
        assert auto["edge_label"] == "contains"

    def test_orphan_without_parent_connects_to_first_group(self):
        """Orphan at depth 2+ with no parent_title connects to first depth-1 group."""
        topics = _connectivity_topics()
        # Remove parent_title from Concept Y
        topics[4]["parent_title"] = None
        # Edges cover all except Concept Y
        edges = [
            {"from_title": "Root", "to_title": "Group A", "edge_category": "hierarchy", "edge_label": "contains", "reasoning": "r"},
            {"from_title": "Root", "to_title": "Group B", "edge_category": "hierarchy", "edge_label": "contains", "reasoning": "r"},
            {"from_title": "Group A", "to_title": "Concept X", "edge_category": "hierarchy", "edge_label": "contains", "reasoning": "r"},
            {"from_title": "Group B", "to_title": "Concept Z", "edge_category": "hierarchy", "edge_label": "contains", "reasoning": "r"},
        ]
        validator = ConnectivityValidator(root_title="Root")
        result = validator.validate(topics, edges)
        assert len(result) == 5
        auto = result[-1]
        # First depth-1 group in topics list is "Group A"
        assert auto["from_title"] == "Group A"
        assert auto["to_title"] == "Concept Y"

    def test_depth1_orphan_connects_to_root(self):
        """Orphan at depth 1 connects to root."""
        topics = _connectivity_topics()
        # Edges cover all except Group B (depth-1 orphan)
        edges = [
            {"from_title": "Root", "to_title": "Group A", "edge_category": "hierarchy", "edge_label": "contains", "reasoning": "r"},
            {"from_title": "Group A", "to_title": "Concept X", "edge_category": "hierarchy", "edge_label": "contains", "reasoning": "r"},
            {"from_title": "Group A", "to_title": "Concept Y", "edge_category": "hierarchy", "edge_label": "contains", "reasoning": "r"},
            {"from_title": "Concept Z", "to_title": "Concept X", "edge_category": "association", "edge_label": "related", "reasoning": "r"},
        ]
        validator = ConnectivityValidator(root_title="Root")
        result = validator.validate(topics, edges)
        # Group B is orphan at depth 1 with parent_title="Root" → connects to Root
        auto = [e for e in result if e["to_title"] == "Group B"]
        assert len(auto) == 1
        assert auto[0]["from_title"] == "Root"
        assert auto[0]["edge_category"] == "hierarchy"

    def test_root_itself_not_flagged_as_orphan(self):
        """Root node is skipped even if it only has outgoing edges."""
        topics = _connectivity_topics()
        # Root only appears as from_title, never as to_title
        edges = [
            {"from_title": "Root", "to_title": "Group A", "edge_category": "hierarchy", "edge_label": "contains", "reasoning": "r"},
            {"from_title": "Root", "to_title": "Group B", "edge_category": "hierarchy", "edge_label": "contains", "reasoning": "r"},
            {"from_title": "Group A", "to_title": "Concept X", "edge_category": "hierarchy", "edge_label": "contains", "reasoning": "r"},
            {"from_title": "Group A", "to_title": "Concept Y", "edge_category": "hierarchy", "edge_label": "contains", "reasoning": "r"},
            {"from_title": "Group B", "to_title": "Concept Z", "edge_category": "hierarchy", "edge_label": "contains", "reasoning": "r"},
        ]
        validator = ConnectivityValidator(root_title="Root")
        result = validator.validate(topics, edges)
        # No new edges — root is connected via from_title, and is explicitly skipped
        assert len(result) == 5

    def test_raises_if_auto_connect_impossible(self):
        """No root and no groups available → raises ValidationError."""
        topics = [
            {"title": "Orphan A", "depth": 2, "parent_title": None},
            {"title": "Orphan B", "depth": 2, "parent_title": None},
        ]
        edges = [
            {"from_title": "Orphan A", "to_title": "Orphan B", "edge_category": "association", "edge_label": "related", "reasoning": "r"},
        ]
        # Orphan A and Orphan B are both connected. But if we add a third orphan:
        topics.append({"title": "Orphan C", "depth": 2, "parent_title": None})
        validator = ConnectivityValidator(root_title=None)
        with pytest.raises(ValidationError, match="Cannot auto-connect"):
            validator.validate(topics, edges)
