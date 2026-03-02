"""OpenAI chat completions wrapper with JSON prompts for all pipeline stages."""
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

5. Every topic must map to at least one chunk by its index. A chunk may be mapped to multiple topics if it covers multiple concepts. Use the "source_page_indices" field to record which chunks support each topic.

6. Topic titles must be concise: 3-8 words. Use noun phrases, not sentences. Examples: "Binary Search Trees," "TCP Three-Way Handshake," "Normal Distribution Properties."

7. Topic descriptions must be 1-2 sentences explaining what the topic covers and what a student will learn from it.

8. For each topic, provide 3-5 keywords — specific terms that appear in the material and are central to the topic. These are used for search and retrieval matching.

9. The "parent_title" field must be null for depth-1 topics. For all other topics, it must exactly match the title of an existing topic at a shallower depth.

10. Avoid creating single-child parents. If a major section would have only one subtopic, either merge them into one topic or check if the section can be split differently.

Respond in the required JSON format:
{{"topics": [{{"title": "string", "description": "string", "depth": "integer", "parent_title": "string or null", "source_page_indices": ["integer"], "keywords": ["string"]}}]}}"""

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

MERGE_DECISION_SYSTEM = """You are a curriculum analyst. Given an existing knowledge graph and newly extracted topics from a new lecture document, decide how to merge the new topics into the existing graph."""

MERGE_DECISION_USER = """Existing graph nodes:
---
{existing_nodes}
---

Newly extracted topics from new document:
---
{new_topics}
---

For each new topic, decide ONE action:
1. NEW: This is a genuinely new concept not covered by any existing node. Create a new node.
2. EXTEND: This topic overlaps with an existing node. Add the new source pages to the existing node and optionally update its description.
3. SKIP: This topic is fully covered by an existing node. No changes needed.

Rules:
- Match by conceptual similarity, not just title. "Binary Trees" and "Binary Tree Data Structures" are the same concept.
- When extending, provide the exact existing node title to extend.
- When creating NEW, provide full topic metadata (title, description, depth, keywords).
- Be conservative: prefer EXTEND over NEW when there is significant overlap.

Respond in JSON:
{{"decisions": [{{"new_title": "string", "action": "NEW|EXTEND|SKIP", "existing_node_title": "string or null", "description": "string or null", "depth": "integer or null", "keywords": ["string"] or null, "source_page_indices": [integer], "reasoning": "string"}}]}}"""

REFERENCE_EXTRACTION_SYSTEM = """You are an academic analyst. Extract textbook and reference citations from lecture material."""

REFERENCE_EXTRACTION_USER = """Lecture pages:
---
{pages}
---

Extract any textbook references, recommended readings, or citations mentioned. Look for:
- Book titles and authors
- ISBN numbers
- URLs to external resources
- "Recommended reading" or "References" sections

Only extract explicitly mentioned references. Do not invent or guess references.

Respond in JSON:
{{"references": [{{"title": "string", "author": "string or null", "isbn": "string or null", "url": "string or null", "ref_type": "book or url"}}]}}"""

ENRICH_SYSTEM = """You are an educational content writer. Given a topic and supplementary search results, write a clear, concise explanation that supplements the lecture material."""

ENRICH_USER = """Topic: {title}
Keywords: {keywords}

Original lecture content:
---
{page_text}
---

Supplementary search results:
---
{search_results}
---

Write a clear 2-4 paragraph supplementary explanation that:
1. Fills gaps in the lecture content
2. Provides additional context and examples
3. Uses precise technical language
4. Does NOT repeat what the lecture already covers

Respond with just the explanation text, no JSON wrapping."""

ORGANIZE_SYSTEM = """You are a curriculum designer. Analyze a knowledge graph and suggest organizational improvements."""

ORGANIZE_USER = """Knowledge graph nodes and their relationships:
---
{graph_json}
---

Propose organizational improvements. Available suggestion types:
1. MERGE: Two nodes that cover the same concept and should be combined (union their page references).
2. SPLIT: One node that covers too many distinct concepts and should be split into separate nodes.
3. REORDER: A node whose order_index should change for better pedagogical sequencing among siblings.
4. REPARENT: A node whose parent/depth should change for better hierarchy.

Rules:
- Be conservative. Only suggest changes with clear benefit.
- For MERGE: provide both node titles and a merged title.
- For SPLIT: provide the node title and proposed sub-nodes with which page references go where.
- For REORDER: provide the node title and new suggested order_index.
- For REPARENT: provide the node title and new parent title (or null for depth 1).
- Include reasoning for each suggestion.
- Maximum 10 suggestions.

Respond in JSON:
{{"suggestions": [{{"type": "MERGE|SPLIT|REORDER|REPARENT", "node_titles": ["string"], "merged_title": "string or null", "new_parent_title": "string or null", "new_order_index": "integer or null", "split_into": [{{"title": "string", "page_ids": ["string"]}}] or null, "reasoning": "string"}}]}}"""


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

    def merge_topics(self, existing_nodes: list[dict], new_topics: list[dict]) -> dict:
        """LLM Call 3: Decide how to merge new topics into existing graph."""
        user_prompt = MERGE_DECISION_USER.format(
            existing_nodes=json.dumps(existing_nodes, indent=2),
            new_topics=json.dumps(new_topics, indent=2),
        )
        return self._call(MERGE_DECISION_SYSTEM, user_prompt)

    def extract_references(self, pages: list[dict]) -> dict:
        """Extract textbook/URL references from lecture pages."""
        user_prompt = REFERENCE_EXTRACTION_USER.format(
            pages=json.dumps(pages, indent=2),
        )
        return self._call(REFERENCE_EXTRACTION_SYSTEM, user_prompt)

    def enrich_topic(self, title: str, keywords: list[str], page_text: str, search_results: str) -> str:
        """Generate supplementary content for a topic using search results."""
        user_prompt = ENRICH_USER.format(
            title=title,
            keywords=", ".join(keywords),
            page_text=page_text,
            search_results=search_results,
        )
        response = self.client.chat.completions.create(
            model=self.model,
            temperature=0.3,
            messages=[
                {"role": "system", "content": ENRICH_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
        )
        return response.choices[0].message.content

    def suggest_organization(self, graph_json: list[dict]) -> dict:
        """Suggest organizational improvements for a knowledge graph."""
        user_prompt = ORGANIZE_USER.format(
            graph_json=json.dumps(graph_json, indent=2),
        )
        return self._call(ORGANIZE_SYSTEM, user_prompt)
