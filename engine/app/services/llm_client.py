"""OpenAI chat completions wrapper with JSON prompts for all pipeline stages."""
import json
import logging
import time

from openai import OpenAI

logger = logging.getLogger(__name__)

# =========================
# Stage 1 — TOPIC EXTRACTION
# =========================

TOPIC_EXTRACTION_SYSTEM = """You are a curriculum analyst. Given lecture material, extract a clean hierarchical topic outline like a textbook table of contents.

You must follow these constraints:
- Use ONLY what is explicitly present in the material (no invention).
- Prefer conceptual structure over slide/page boundaries.
- Output MUST be valid JSON matching the specified shape and types.
- Do NOT include any text outside the JSON object.
"""

TOPIC_EXTRACTION_USER = """Lecture Material Chunks (JSON array; each element has an index implicitly by array position):
---
{chunks}
---

Maximum hierarchy depth: {max_depth}
Course title: {course_title}

Task:
Extract a hierarchical topic outline from this material in TWO internal steps (do not show steps; output JSON only):
1) OUTLINE: Design a clean hierarchical outline (like a TOC) based on conceptual structure.
2) MAP: Map each topic to supporting chunk indices.

Rules:
1) ONLY extract topics explicitly covered in the material. Do not invent or speculate.
2) Each concept is a distinct teachable unit.
3) Hierarchy requirements:
   - Depth 1: MUST be "group" nodes only (broad sections). No concepts at depth 1.
   - Depth 2+: Concepts and sub-groups.
   - Prefer deeper nesting over wide flat lists.
   - If >6 siblings under one parent, create a sub-group to cluster them.
   - Do not exceed depth {max_depth}; flatten deeper items to {max_depth}.
4) node_type:
   - "group" if it contains subtopics (organizational container)
   - "concept" if it is a leaf teaching unit
5) "Miscellaneous" already exists at depth 1:
   - Put tangential or administrative content there by setting parent_title = "Miscellaneous".
6) Admin/meta content MUST be ignored entirely:
   - quiz announcements, exam schedules, grading policies, agendas, acknowledgements, thank-you slides,
     course logistics, title-only slides with no substantive teaching content.
   - These chunks MUST NOT create topics and MUST NOT appear in source_page_indices.
7) source_page_indices:
   - MUST be an array of INTEGERS (chunk indices).
   - Groups may be [].
   - Concepts should reference at least one chunk index (unless truly absent, in which case omit the concept).
8) Titles:
   - Concise noun phrases, 3–8 words. No trailing punctuation.
9) Descriptions:
   - 1–2 sentences describing what the student learns.
10) Keywords:
   - 3–5 specific terms from the material.

Output shape constraints (MUST follow exactly; no extra keys):
- Top-level keys: ["topics"]
- Each topic object keys (exactly):
  ["title","description","depth","parent_title","node_type","source_page_indices","keywords"]
- Types:
  - title: string
  - description: string
  - depth: integer
  - parent_title: string or null
  - node_type: "group" or "concept"
  - source_page_indices: array of integers
  - keywords: array of strings

Respond in JSON only:
{{"topics":[{{"title":"string","description":"string","depth":1,"parent_title":null,"node_type":"group","source_page_indices":[],"keywords":["string"]}}]}}"""


# ============================
# Stage 2 — DEPENDENCY INFERENCE
# ============================

DEPENDENCY_INFERENCE_SYSTEM = """You are a curriculum designer. Given extracted topics, determine relationships between them.

You must follow these constraints:
- Use ONLY the provided topics/titles (no renaming, no new nodes).
- Output MUST be valid JSON matching the specified shape.
- Do NOT include any text outside the JSON object.
"""

DEPENDENCY_INFERENCE_USER = """Topics extracted from lecture material:
---
{topics_json}
---

Root node context: {root_context}

Task:
Propose edges among the provided topics.

Edge categories:
- "dependency": A should be understood before B (directional prerequisite).
- "association": A and B are related but neither strictly depends on the other.
- "hierarchy": A contains B (structural containment).

Rules:
1) Title integrity:
   - Use the EXACT topic titles from the input (case/punctuation must match).
   - Do not abbreviate or rename titles.
2) Connectivity:
   - EVERY concept node (node_type="concept") MUST have at least one NON-HIERARCHY edge
     (dependency or association). If no true prerequisite exists, add a single association edge
     to the closest sibling or nearest related node.
3) Dependency constraints:
   - No cycles among dependency edges.
   - Each topic should have at most 3 incoming dependency edges.
   - Depth-1 topics must NOT have incoming dependency edges.
4) Hierarchy constraints:
   - If a root node exists at depth 0, add hierarchy edges from root to EVERY depth-1 group with label "contains".
   - Do NOT create dependency/association edges to/from the root node.
   - Do NOT create hierarchy edges that contradict the extracted hierarchy (i.e., do not attach a child under an unrelated parent).
5) Edge label:
   - 2–5 words, readable as "A [label] B" along direction A -> B.
6) Provide 1-sentence reasoning per edge.

Output shape constraints (MUST follow exactly; no extra keys):
- Top-level keys: ["edges"]
- Each edge object keys (exactly):
  ["from_title","to_title","edge_category","edge_label","reasoning"]

Respond in JSON only:
{{"edges":[{{"from_title":"string","to_title":"string","edge_category":"dependency|association|hierarchy","edge_label":"string","reasoning":"string"}}]}}"""


# =====================
# Stage 3 — MERGE DECISION
# =====================

MERGE_DECISION_SYSTEM = """You are a curriculum analyst. Given an existing knowledge graph and newly extracted topics from a new lecture document, decide how to merge the new topics into the existing graph.

You must follow these constraints:
- Match by conceptual similarity, not exact title equality.
- Output MUST be valid JSON matching the specified shape.
- Do NOT include any text outside the JSON object.
"""

MERGE_DECISION_USER = """Existing graph nodes:
---
{existing_nodes}
---

Newly extracted topics from new document:
---
{new_topics}
---

For each new topic, choose exactly ONE action:
1) NEW: genuinely new concept not covered by any existing node.
2) EXTEND: overlaps with an existing node — add new source pages to that node (and optionally adjust description).
3) SKIP: fully covered by an existing node.

Rules:
- Prefer EXTEND over NEW when there is meaningful overlap.
- When EXTEND, provide the exact existing_node_title to extend (must match an existing node title exactly).
- When NEW, provide full topic metadata (title, description, depth, keywords).
- source_page_indices MUST be an array of integers.

Output shape constraints (MUST follow exactly; no extra keys):
- Top-level keys: ["decisions"]
- Each decision object keys (exactly):
  ["new_title","action","existing_node_title","description","depth","keywords","source_page_indices","reasoning"]

Respond in JSON only:
{{"decisions":[{{"new_title":"string","action":"NEW|EXTEND|SKIP","existing_node_title":"string or null","description":"string or null","depth":0,"keywords":["string"] or null,"source_page_indices":[0],"reasoning":"string"}}]}}"""


# =========================
# Stage 0.5 — REFERENCE EXTRACTION
# =========================

REFERENCE_EXTRACTION_SYSTEM = """You are an academic analyst. Extract textbook and reference citations explicitly mentioned in lecture material.

Constraints:
- Extract ONLY explicit references (no guessing).
- Output MUST be valid JSON matching the specified shape.
- Do NOT include any text outside the JSON object.
"""

REFERENCE_EXTRACTION_USER = """Lecture pages:
---
{pages}
---

Extract any explicitly mentioned:
- textbook titles/authors
- ISBNs
- URLs
- "Recommended reading" / "References" items

Output shape constraints (MUST follow exactly; no extra keys):
- Top-level keys: ["references"]
- Each reference object keys (exactly):
  ["title","author","isbn","url","ref_type"]

Respond in JSON only:
{{"references":[{{"title":"string","author":"string or null","isbn":"string or null","url":"string or null","ref_type":"book|url"}}]}}"""


# ==========
# Stage 3 — ENRICH
# ==========

ENRICH_SYSTEM = """You are an educational content writer. Given a topic and supplementary search results, write a concise supplement that helps a student.

Constraints:
- Do NOT contradict the lecture content.
- If the search results do not clearly support a claim, omit it.
- Do NOT repeat the lecture verbatim.
- Output MUST be plain text only (no JSON, no markdown fences).
"""

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

Write a clear 2–4 paragraph supplementary explanation that:
1) Fills gaps in the lecture content
2) Adds context and examples
3) Uses precise technical language
4) Avoids repeating what the lecture already covers
5) Omits any claim not supported by the search results

Return ONLY the explanation text."""


# ==========================
# Stage 4 — ORGANIZE (UPDATED)
# ==========================

ORGANIZE_SYSTEM = """You are a curriculum organizer. Your job is to improve the organizational quality of an existing course knowledge graph.

Primary objective (must enforce):
- NO orphaned groups. Every non-root group must have a hierarchy path that leads to the course root (depth 0).
- All groups must ultimately lead to the course title/root via hierarchy edges.

Constraints:
- Base decisions on logical structure (depth, hierarchy edges, titles, source_documents, page_ids, edge categories).
- Ignore any visual/layout metadata if present (x/y/width/height/layer/routing/etc).
- Be conservative with changes that could delete or radically restructure content unless there is clear redundancy.
- Output MUST be valid JSON matching the specified shape.
- Do NOT include any text outside the JSON object.
"""

ORGANIZE_USER = """Knowledge graph nodes and their relationships (JSON array of nodes):
---
{graph_json}
---

Graph semantics:
- node_type: "group" (organizational container) or "concept" (teachable unit)
- hierarchy edges represent containment and define the path to the root
- dependency/association edges are conceptual links (do not define parent/child)

Your task:
Propose organizational improvements to produce a clean hierarchy with minimal redundancy, while enforcing:

HARD INVARIANTS (must address if violated):
1) Root (depth 0, node_type="group") must ONLY connect to depth-1 groups via hierarchy edges.
2) Every depth-1 group must be reachable from the root by a hierarchy edge (root -> depth-1).
3) Every non-root group (node_type="group", depth>=1) must have at least one incoming hierarchy edge from a parent group.
4) Every node (group or concept) must have a hierarchy path that eventually reaches the root through parent groups.
   - If a node is not on such a path, it is orphaned: you MUST fix it using REPARENT or CREATE_GROUP.
5) Do NOT propose changes to the root node itself (no MERGE/SPLIT/REORDER/REPARENT/DISSOLVE_GROUP on root).

Secondary goals:
- Merge clear duplicates (especially across different source_documents) when titles/keywords/page_ids strongly overlap.
- Reduce redundancy and improve pedagogical sequencing.
- Prefer deeper hierarchy over flat lists; if 5+ concept nodes share a parent, consider CREATE_GROUP.
- Do not create new concepts; only reorganize existing ones.

Available suggestion types (output MUST use only these):
1) MERGE: Combine 2+ nodes that cover the same concept (provide node_titles + merged_title).
2) SPLIT: Break a broad node into 2+ sub-nodes (provide split_into with page_ids).
3) REORDER: Adjust order_index for sibling ordering (provide new_order_index).
4) REPARENT: Move a node under a different parent group OR to depth 1 (provide new_parent_title or null).
5) CREATE_GROUP: Create a new group node to cluster related existing nodes (provide group_title + children list).
6) DISSOLVE_GROUP: Remove a group node that adds no value, promoting its children (node_titles = [group_title]).

Rules:
- No maximum suggestions. However prefer fewer, higher-confidence suggestions.
- For orphan fixes: prioritize REPARENT first; use CREATE_GROUP when no appropriate parent exists.
- For MERGE: only merge when there is strong evidence (high semantic overlap OR shared page_ids OR shared keywords + close placement).
- Avoid speculative SPLIT unless clearly multi-topic.
- Any REPARENT must choose a target parent that is a group node.
- Do NOT suggest MERGE/SPLIT/REORDER/REPARENT/DISSOLVE_GROUP for the root node (depth 0).

Output shape constraints (MUST follow exactly; no extra keys):
Top-level: {{"suggestions": [...]}}
Each suggestion object keys (exactly):
["type","node_titles","merged_title","group_title","children","new_parent_title","new_order_index","split_into","reasoning"]

Respond in JSON only:
{{"suggestions":[{{"type":"MERGE|SPLIT|REORDER|REPARENT|CREATE_GROUP|DISSOLVE_GROUP","node_titles":["string"],"merged_title":null,"group_title":null,"children":null,"new_parent_title":null,"new_order_index":null,"split_into":null,"reasoning":"string"}}]}}"""


# =========================
# Root title generator (optional)
# =========================

TOPIC_TITLE_SYSTEM = """You are a curriculum analyst. Given extracted topics from lecture material, generate a concise descriptive title that captures the overall subject matter.

Constraints:
- Use ONLY what is reflected by the extracted topics.
- Output MUST be valid JSON matching the specified shape.
- Do NOT include any text outside the JSON object.
"""

TOPIC_TITLE_USER = """Course title: {course_title}

Extracted topics:
---
{topics_json}
---

Generate a descriptive topic title (5–10 words) capturing the subject matter covered by these topics.
This will be used as the course root node title.

Output shape constraints (MUST follow exactly; no extra keys):
{{"topic_title":"string"}}
"""


class LLMClient:
    """Thin wrapper over OpenAI chat completions for structured JSON extraction."""

    def __init__(self, api_key: str, model: str = "gpt-4o-mini"):
        self.client = OpenAI(api_key=api_key)
        self.model = model

    def _call(self, system: str, user: str, label: str = "unknown") -> dict:
        """Make a chat completion call and return parsed JSON."""
        prompt_chars = len(system) + len(user)
        logger.info("[LLM] %s — sending %d chars to %s", label, prompt_chars, self.model)
        t0 = time.perf_counter()
        response = self.client.chat.completions.create(
            model=self.model,
            temperature=0.2,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        elapsed = time.perf_counter() - t0
        usage = response.usage
        tokens_info = f"in={usage.prompt_tokens} out={usage.completion_tokens}" if usage else "no usage data"
        logger.info("[LLM] %s — done in %.1fs (%s)", label, elapsed, tokens_info)
        return json.loads(response.choices[0].message.content)

    def extract_topics(self, chunks: list[dict], max_depth: int = 4, course_title: str = "") -> dict:
        """LLM Call 1: Extract hierarchical topics from page-grouped chunks."""
        user_prompt = TOPIC_EXTRACTION_USER.format(
            chunks=json.dumps(chunks, indent=2),
            max_depth=max_depth,
            course_title=course_title,
        )
        return self._call(TOPIC_EXTRACTION_SYSTEM, user_prompt, label="extract_topics")

    def infer_dependencies(self, topics: list[dict], root_title: str | None = None) -> dict:
        """LLM Call 2: Infer prerequisite/related edges between topics."""
        root_context = f'A root node "{root_title}" exists at depth 0. It is the parent of all depth-1 groups.' if root_title else "No root node."
        user_prompt = DEPENDENCY_INFERENCE_USER.format(
            topics_json=json.dumps(topics, indent=2),
            root_context=root_context,
        )
        return self._call(DEPENDENCY_INFERENCE_SYSTEM, user_prompt, label="infer_dependencies")

    def merge_topics(self, existing_nodes: list[dict], new_topics: list[dict]) -> dict:
        """LLM Call 3: Decide how to merge new topics into existing graph."""
        user_prompt = MERGE_DECISION_USER.format(
            existing_nodes=json.dumps(existing_nodes, indent=2),
            new_topics=json.dumps(new_topics, indent=2),
        )
        return self._call(MERGE_DECISION_SYSTEM, user_prompt, label="merge_topics")

    def extract_references(self, pages: list[dict]) -> dict:
        """Extract textbook/URL references from lecture pages."""
        user_prompt = REFERENCE_EXTRACTION_USER.format(
            pages=json.dumps(pages, indent=2),
        )
        return self._call(REFERENCE_EXTRACTION_SYSTEM, user_prompt, label="extract_references")

    def enrich_topic(self, title: str, keywords: list[str], page_text: str, search_results: str) -> str:
        """Generate supplementary content for a topic using search results."""
        user_prompt = ENRICH_USER.format(
            title=title,
            keywords=", ".join(keywords),
            page_text=page_text,
            search_results=search_results,
        )
        prompt_chars = len(ENRICH_SYSTEM) + len(user_prompt)
        logger.info("[LLM] enrich_topic '%s' — sending %d chars to %s", title, prompt_chars, self.model)
        t0 = time.perf_counter()
        response = self.client.chat.completions.create(
            model=self.model,
            temperature=0.3,
            messages=[
                {"role": "system", "content": ENRICH_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
        )
        elapsed = time.perf_counter() - t0
        usage = response.usage
        tokens_info = f"in={usage.prompt_tokens} out={usage.completion_tokens}" if usage else "no usage data"
        logger.info("[LLM] enrich_topic '%s' — done in %.1fs (%s)", title, elapsed, tokens_info)
        return response.choices[0].message.content

    def suggest_organization(self, graph_json: list[dict]) -> dict:
        """Suggest organizational improvements for a knowledge graph."""
        user_prompt = ORGANIZE_USER.format(
            graph_json=json.dumps(graph_json, indent=2),
        )
        return self._call(ORGANIZE_SYSTEM, user_prompt, label="suggest_organization")

    def generate_topic_title(self, topics: list[dict], course_title: str) -> dict:
        """Generate a descriptive topic title for the knowledge graph root node."""
        user_prompt = TOPIC_TITLE_USER.format(
            topics_json=json.dumps(topics, indent=2),
            course_title=course_title,
        )
        return self._call(TOPIC_TITLE_SYSTEM, user_prompt, label="generate_topic_title")
