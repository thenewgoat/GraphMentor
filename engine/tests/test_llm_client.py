"""Tests for LLM client methods with mocked OpenAI JSON responses."""
import json
from unittest.mock import MagicMock, patch

import pytest

from app.services.llm_client import LLMClient


class TestLLMClient:
    @patch("app.services.llm_client.OpenAI")
    def test_extract_topics_returns_parsed_json(self, mock_openai_class):
        expected = {"topics": [{"title": "Test Topic", "depth": 1}]}
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps(expected)

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai_class.return_value = mock_client

        llm = LLMClient(api_key="fake", model="gpt-4o-mini")
        result = llm.extract_topics(
            chunks=[{"index": 0, "text": "Hello", "page_number": 1, "heading": None}],
            max_depth=3,
        )

        assert result == expected
        mock_client.chat.completions.create.assert_called_once()
        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert call_kwargs["model"] == "gpt-4o-mini"
        assert call_kwargs["temperature"] == 0.2
        assert call_kwargs["response_format"] == {"type": "json_object"}

    @patch("app.services.llm_client.OpenAI")
    def test_infer_dependencies_returns_parsed_json(self, mock_openai_class):
        expected = {"edges": [{"from_title": "A", "to_title": "B", "edge_type": "prerequisite", "reasoning": "A is needed for B"}]}
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps(expected)

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai_class.return_value = mock_client

        llm = LLMClient(api_key="fake", model="gpt-4o-mini")
        result = llm.infer_dependencies(
            topics=[{"title": "A", "description": "desc", "keywords": ["a"], "depth": 1}],
        )

        assert result == expected

    @patch("app.services.llm_client.OpenAI")
    def test_merge_topics_returns_parsed_json(self, mock_openai_class):
        expected = {"decisions": [{"new_title": "X", "action": "NEW", "reasoning": "new concept"}]}
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps(expected)

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai_class.return_value = mock_client

        llm = LLMClient(api_key="fake")
        result = llm.merge_topics(
            existing_nodes=[{"title": "A", "depth": 1}],
            new_topics=[{"title": "X", "depth": 1}],
        )
        assert result == expected

    @patch("app.services.llm_client.OpenAI")
    def test_extract_references_returns_parsed_json(self, mock_openai_class):
        expected = {"references": [{"title": "CLRS", "ref_type": "book"}]}
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps(expected)

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai_class.return_value = mock_client

        llm = LLMClient(api_key="fake")
        result = llm.extract_references(pages=[{"index": 0, "text": "See CLRS"}])
        assert result == expected

    @patch("app.services.llm_client.OpenAI")
    def test_enrich_topic_returns_text(self, mock_openai_class):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Supplementary explanation here."

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai_class.return_value = mock_client

        llm = LLMClient(api_key="fake")
        result = llm.enrich_topic(
            title="Binary Trees",
            keywords=["tree", "binary"],
            page_text="Binary trees are...",
            search_results="Wikipedia: A binary tree...",
        )
        assert result == "Supplementary explanation here."

    @patch("app.services.llm_client.OpenAI")
    def test_suggest_organization_returns_parsed_json(self, mock_openai_class):
        expected = {"suggestions": [{"type": "MERGE", "node_titles": ["A", "B"], "reasoning": "same concept"}]}
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps(expected)

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai_class.return_value = mock_client

        llm = LLMClient(api_key="fake")
        result = llm.suggest_organization(graph_json=[{"title": "A"}, {"title": "B"}])
        assert result == expected
