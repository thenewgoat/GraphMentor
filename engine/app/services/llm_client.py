# engine/app/services/llm_client.py
import json
import logging

from openai import OpenAI

logger = logging.getLogger(__name__)

TOPIC_EXTRACTION_SYSTEM = """You are a curriculum analyst. Given lecture material chunks with metadata, extract a hierarchical topic structure. Each topic should represent a distinct teachable concept. Organize topics into a parent-child hierarchy where children are subtopics of their parent. Do NOT invent topics not present in the material — only extract what is explicitly covered."""

TOPIC_EXTRACTION_USER = """Lecture Material Chunks:
---
{chunks}
---

Maximum hierarchy depth: {max_depth}

Analyze the lecture material above and extract a hierarchical topic structure. Follow these rules:

1. ONLY extract topics that are explicitly covered in the provided chunks. Do not invent, infer, or speculate about topics that are not present in the material.

2. Each topic must represent a distinct, teachable concept — something a student would need to understand as a discrete learning unit.

3. Organize topics into a parent-child hierarchy:
   - Depth 1: Major course sections or top-level themes. These are broad organizing categories.
   - Depth 2: Subtopics within a major section. These are the primary teaching units.
   - Depth 3+ (up to max_depth {max_depth}): More granular sub-subtopics, only if the material is detailed enough to warrant them.

4. Do not exceed depth {max_depth}. If the material suggests deeper nesting, flatten the deeper topics to depth {max_depth}.

5. Every topic must map to at least one chunk by its index. A chunk may be mapped to multiple topics if it covers multiple concepts. Use the "source_chunk_indices" field to record which chunks support each topic.

6. Topic titles must be concise: 3-8 words. Use noun phrases, not sentences. Examples: "Binary Search Trees," "TCP Three-Way Handshake," "Normal Distribution Properties."

7. Topic descriptions must be 1-2 sentences explaining what the topic covers and what a student will learn from it.

8. For each topic, provide 3-5 keywords — specific terms that appear in the material and are central to the topic. These are used for search and retrieval matching.

9. The "parent_title" field must be null for depth-1 topics. For all other topics, it must exactly match the title of an existing topic at a shallower depth.

10. Avoid creating single-child parents. If a major section would have only one subtopic, either merge them into one topic or check if the section can be split differently.

Respond in the required JSON format:
{{"topics": [{{"title": "string", "description": "string", "depth": "integer", "parent_title": "string or null", "source_chunk_indices": ["integer"], "keywords": ["string"]}}]}}"""

DEPENDENCY_INFERENCE_SYSTEM = """You are a curriculum designer. Given a list of topics extracted from lecture material, determine the prerequisite dependencies between them. A prerequisite edge means "Topic A must be understood before Topic B can be learned." A related edge means "Topics are connected but neither is strictly required first." Only create edges where there is a clear logical dependency or relationship. Do NOT over-connect — prefer fewer, stronger edges."""

DEPENDENCY_INFERENCE_USER = """Topics extracted from lecture material:
---
{topics_json}
---

Determine the prerequisite and related edges between these topics. Follow these rules:

1. A "prerequisite" edge from Topic A to Topic B means: "A student must understand Topic A before they can learn Topic B." Only create prerequisite edges where there is a clear logical dependency — Topic B's content fundamentally relies on concepts from Topic A.

2. A "related" edge means: "These topics are conceptually connected, but understanding one is not strictly required before learning the other." Use related edges sparingly — only when there is a meaningful connection that would help a student see the bigger picture.

3. Prefer FEWER, STRONGER edges over many weak ones. Not every pair of topics needs an edge. If in doubt, do not create the edge.

4. Each topic should have at most 3 incoming prerequisite edges. If a topic logically depends on more than 3 prerequisites, keep only the 3 most critical ones.

5. Root topics (depth 1) must NOT have any incoming prerequisite edges. They may have "related" edges between them, but these should be rare.

6. Edges must NOT form cycles. The prerequisite edges must form a Directed Acyclic Graph (DAG). Before including an edge, consider whether it would create a circular dependency.

7. Cross-depth edges are allowed. A depth-2 topic may be a prerequisite for another depth-2 topic under a different parent. However, prefer edges that respect the natural hierarchy (parent-to-child) when possible.

8. For each edge, provide a brief reasoning (1 sentence) explaining WHY the dependency exists. Be specific — reference the concepts involved, not generic statements like "these are related."

9. Use the exact topic titles from the input. Do not rename or abbreviate them.

Respond in the required JSON format:
{{"edges": [{{"from_title": "string", "to_title": "string", "edge_type": "prerequisite or related", "reasoning": "string"}}]}}"""


class LLMClient:
    """Thin wrapper over OpenAI chat completions for structured JSON extraction."""

    def __init__(self, api_key: str, model: str = "gpt-4o-mini"):
        self.client = OpenAI(api_key=api_key)
        self.model = model

    def _call(self, system: str, user: str) -> dict:
        """Make a chat completion call and return parsed JSON."""
        logger.info(f"LLM call with model={self.model}")
        response = self.client.chat.completions.create(
            model=self.model,
            temperature=0.2,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return json.loads(response.choices[0].message.content)

    def extract_topics(self, chunks: list[dict], max_depth: int = 3) -> dict:
        """LLM Call 1: Extract hierarchical topics from page-grouped chunks."""
        user_prompt = TOPIC_EXTRACTION_USER.format(
            chunks=json.dumps(chunks, indent=2),
            max_depth=max_depth,
        )
        return self._call(TOPIC_EXTRACTION_SYSTEM, user_prompt)

    def infer_dependencies(self, topics: list[dict]) -> dict:
        """LLM Call 2: Infer prerequisite/related edges between topics."""
        user_prompt = DEPENDENCY_INFERENCE_USER.format(
            topics_json=json.dumps(topics, indent=2),
        )
        return self._call(DEPENDENCY_INFERENCE_SYSTEM, user_prompt)
