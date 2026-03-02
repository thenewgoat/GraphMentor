import pytest

from app.services.validators import TopicValidator, ValidationError


def _valid_topics():
    """Minimal valid topic extraction response."""
    return {
        "topics": [
            {
                "title": "Machine Learning Basics",
                "description": "Introduction to ML concepts.",
                "depth": 1,
                "parent_title": None,
                "source_chunk_indices": [0, 1],
                "keywords": ["machine learning", "supervised", "unsupervised"],
            },
            {
                "title": "Linear Regression",
                "description": "Fitting a line to data points.",
                "depth": 2,
                "parent_title": "Machine Learning Basics",
                "source_chunk_indices": [1],
                "keywords": ["regression", "linear", "least squares"],
            },
            {
                "title": "Decision Trees",
                "description": "Tree-based classification and regression.",
                "depth": 2,
                "parent_title": "Machine Learning Basics",
                "source_chunk_indices": [2],
                "keywords": ["decision tree", "split", "entropy"],
            },
        ]
    }


class TestTopicValidator:
    def test_valid_response_passes(self):
        validator = TopicValidator(num_chunks=3, max_depth=3)
        result = validator.validate(_valid_topics())
        assert result == _valid_topics()

    def test_duplicate_titles_rejected(self):
        data = _valid_topics()
        data["topics"][2]["title"] = "Linear Regression"
        validator = TopicValidator(num_chunks=3, max_depth=3)
        with pytest.raises(ValidationError, match="[Dd]uplicate"):
            validator.validate(data)

    def test_invalid_parent_title_rejected(self):
        data = _valid_topics()
        data["topics"][1]["parent_title"] = "Nonexistent Topic"
        validator = TopicValidator(num_chunks=3, max_depth=3)
        with pytest.raises(ValidationError, match="[Pp]arent"):
            validator.validate(data)

    def test_depth_exceeds_max_rejected(self):
        data = _valid_topics()
        data["topics"][1]["depth"] = 4
        validator = TopicValidator(num_chunks=3, max_depth=3)
        with pytest.raises(ValidationError, match="[Dd]epth"):
            validator.validate(data)

    def test_invalid_chunk_index_rejected(self):
        data = _valid_topics()
        data["topics"][0]["source_chunk_indices"] = [0, 99]
        validator = TopicValidator(num_chunks=3, max_depth=3)
        with pytest.raises(ValidationError, match="[Cc]hunk"):
            validator.validate(data)

    def test_empty_chunk_indices_rejected(self):
        data = _valid_topics()
        data["topics"][0]["source_chunk_indices"] = []
        validator = TopicValidator(num_chunks=3, max_depth=3)
        with pytest.raises(ValidationError, match="[Cc]hunk"):
            validator.validate(data)


from app.services.validators import DependencyValidator


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
        assert len(result["edges"]) == 2  # ghost edge removed

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
        # The shorter reasoning ("Cycle.") should be removed
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
        # The shortest reasoning ("Short.") should be removed
        assert all(e["reasoning"] != "Short." for e in prereqs_to_final)
