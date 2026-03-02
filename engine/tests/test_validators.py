"""Tests for topic, merge, and dependency validators with cycle detection."""
import pytest

from app.services.validators import TopicValidator, DependencyValidator, MergeValidator, ValidationError


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
        assert result == _valid_topics()

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

    def test_depth_exceeds_max_rejected(self):
        data = _valid_topics()
        data["topics"][1]["depth"] = 4
        validator = TopicValidator(num_pages=3, max_depth=3)
        with pytest.raises(ValidationError, match="[Dd]epth"):
            validator.validate(data)

    def test_invalid_page_index_rejected(self):
        data = _valid_topics()
        data["topics"][0]["source_page_indices"] = [0, 99]
        validator = TopicValidator(num_pages=3, max_depth=3)
        with pytest.raises(ValidationError, match="[Pp]age"):
            validator.validate(data)

    def test_empty_page_indices_rejected(self):
        data = _valid_topics()
        data["topics"][0]["source_page_indices"] = []
        validator = TopicValidator(num_pages=3, max_depth=3)
        with pytest.raises(ValidationError, match="[Pp]age"):
            validator.validate(data)


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
            {"from_title": "Basics", "to_title": "Intermediate", "edge_type": "prerequisite", "reasoning": "Basics provides foundation for Intermediate concepts."},
            {"from_title": "Intermediate", "to_title": "Advanced", "edge_type": "prerequisite", "reasoning": "Intermediate builds toward Advanced material."},
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
            {"from_title": "Ghost", "to_title": "Intermediate", "edge_type": "prerequisite", "reasoning": "Invalid."}
        )
        validator = DependencyValidator(topics=_topics_for_deps())
        result = validator.validate(data)
        assert len(result["edges"]) == 2

    def test_cycle_detected_and_broken(self):
        data = {
            "edges": [
                {"from_title": "Intermediate", "to_title": "Advanced", "edge_type": "prerequisite", "reasoning": "Intermediate leads to Advanced material."},
                {"from_title": "Advanced", "to_title": "Intermediate", "edge_type": "prerequisite", "reasoning": "Cycle."},
            ]
        }
        validator = DependencyValidator(topics=_topics_for_deps())
        result = validator.validate(data)
        assert len(result["edges"]) == 1
        assert result["edges"][0]["reasoning"] == "Intermediate leads to Advanced material."

    def test_root_topic_protection(self):
        data = {
            "edges": [
                {"from_title": "Intermediate", "to_title": "Basics", "edge_type": "prerequisite", "reasoning": "Should be removed."},
            ]
        }
        validator = DependencyValidator(topics=_topics_for_deps())
        result = validator.validate(data)
        assert len(result["edges"]) == 0

    def test_max_three_prerequisites_enforced(self):
        data = {
            "edges": [
                {"from_title": "Basics", "to_title": "Final", "edge_type": "prerequisite", "reasoning": "First reason is important."},
                {"from_title": "Intermediate", "to_title": "Final", "edge_type": "prerequisite", "reasoning": "Second reason is also very important."},
                {"from_title": "Advanced", "to_title": "Final", "edge_type": "prerequisite", "reasoning": "Third reason is quite important too."},
                {"from_title": "Expert", "to_title": "Final", "edge_type": "prerequisite", "reasoning": "Short."},
            ]
        }
        validator = DependencyValidator(topics=_topics_for_deps())
        result = validator.validate(data)
        prereqs_to_final = [e for e in result["edges"] if e["to_title"] == "Final" and e["edge_type"] == "prerequisite"]
        assert len(prereqs_to_final) == 3
        assert all(e["reasoning"] != "Short." for e in prereqs_to_final)
