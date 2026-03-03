"""OpenAI chat completions wrapper with JSON prompts for all pipeline stages."""
import json
import logging
import time

from openai import OpenAI

logger = logging.getLogger(__name__)

TOPIC_EXTRACTION_SYSTEM = """You are a curriculum analyst. Given lecture material, extract a clean hierarchical topic outline — like an indented table of contents. Think about conceptual structure, NOT page boundaries. Multiple pages may cover one topic; one page may touch several topics. Do NOT invent topics not present in the material."""

TOPIC_EXTRACTION_USER = """Lecture Material Chunks:
---
{chunks}
---

Maximum hierarchy depth: {max_depth}
Course title: {course_title}

Extract a hierarchical topic outline from this material in TWO mental steps:

STEP 1 — OUTLINE FIRST: Read ALL the material, then design a clean hierarchical outline as if you were writing a textbook table of contents. Group related ideas under shared parent topics. Do NOT think about which page each topic came from — focus on the logical structure of the subject matter.

STEP 2 — MAP PAGES: For each topic in your outline, note which chunk indices contain supporting content. A topic may draw from many chunks, and a chunk may support multiple topics. Some topics (especially groups) may have no direct page — that is fine, use an empty list.

Rules:

1. ONLY extract topics explicitly covered in the material. Do not invent or speculate.

2. Each topic is a distinct, teachable concept — something a student would learn as one unit.

3. Build a DEEP hierarchy, not a flat list:
   - Depth 1: Major course sections. These are broad organizing categories. MUST be "group" node_type — no concepts at depth 1.
   - Depth 2: Subtopics within a section. Primary teaching units. May be groups or concepts.
   - Depth 3-{max_depth}: Granular sub-subtopics where the material warrants them. Usually concepts.
   Prefer deeper nesting over wide flat lists. If you have more than 5-6 siblings at any level, consider grouping some under a shared parent.
   All concept nodes (node_type "concept") MUST be at depth 2 or deeper — never at depth 1.

4. node_type: "group" if it contains subtopics (organizational container), "concept" if it is a leaf teaching unit.

5. Depth-1 groups should cluster related concepts, ideally grouping content from 1-3 source documents that cover similar subject matter. If multiple documents cover the same broad area, group their concepts together under one depth-1 group. A group may cover concepts from multiple documents if they are semantically related.

6. A "Miscellaneous" group already exists at depth 1. Put tangential or administrative content there (set parent_title to "Miscellaneous").

7. Do not exceed depth {max_depth}. Flatten deeper topics to depth {max_depth}.

8. source_page_indices: list of chunk indices that support the topic. Groups with no direct content may use an empty list []. Concepts should reference at least one chunk.

9. Titles: concise noun phrases, 3-8 words. Examples: "Binary Search Trees," "TCP Three-Way Handshake."

10. Descriptions: 1-2 sentences on what the topic covers and what a student learns.

11. Keywords: 3-5 specific terms from the material central to the topic.

12. parent_title: null for depth-1 topics. For others, must exactly match a shallower topic's title.

13. SKIP pages that are purely administrative or meta-information: quiz announcements, exam schedules, grading policies, agendas, table of contents, acknowledgements, "thank you" slides, course logistics, or title-only pages with no substantive teaching content. These pages must NOT produce any topics and must NOT appear in any source_page_indices. Only extract topics relevant to the course subject: "{course_title}".

--- FEW-SHOT EXAMPLE ---

For a course titled "Data Structures and Algorithms" covering sorting, trees, and graph traversals, the correct output structure is:

{{"topics": [
  {{"title": "Sorting Algorithms", "description": "Overview of comparison-based and non-comparison sorting methods.", "depth": 1, "parent_title": null, "node_type": "group", "source_page_indices": [], "keywords": ["sorting", "comparison", "time complexity"]}},
  {{"title": "Merge Sort", "description": "Divide-and-conquer sorting algorithm with O(n log n) guaranteed performance.", "depth": 2, "parent_title": "Sorting Algorithms", "node_type": "concept", "source_page_indices": [0, 1], "keywords": ["merge sort", "divide and conquer", "stable sort"]}},
  {{"title": "Quick Sort", "description": "Partition-based sorting with average O(n log n) and in-place operation.", "depth": 2, "parent_title": "Sorting Algorithms", "node_type": "concept", "source_page_indices": [2], "keywords": ["quick sort", "partition", "pivot"]}},
  {{"title": "Tree Data Structures", "description": "Hierarchical data structures for efficient search and organization.", "depth": 1, "parent_title": null, "node_type": "group", "source_page_indices": [], "keywords": ["tree", "binary tree", "traversal"]}},
  {{"title": "Binary Search Trees", "description": "Ordered binary trees supporting efficient lookup, insertion, and deletion.", "depth": 2, "parent_title": "Tree Data Structures", "node_type": "concept", "source_page_indices": [3, 4], "keywords": ["BST", "search", "ordered tree"]}},
  {{"title": "Self-Balancing Trees", "description": "Trees that maintain balance for worst-case logarithmic operations.", "depth": 2, "parent_title": "Tree Data Structures", "node_type": "group", "source_page_indices": [], "keywords": ["balanced", "rotation", "height"]}},
  {{"title": "AVL Trees", "description": "Height-balanced BST using rotations after insertions and deletions.", "depth": 3, "parent_title": "Self-Balancing Trees", "node_type": "concept", "source_page_indices": [5], "keywords": ["AVL", "rotation", "balance factor"]}},
  {{"title": "Red-Black Trees", "description": "Self-balancing BST with color-based invariants for guaranteed O(log n) operations.", "depth": 3, "parent_title": "Self-Balancing Trees", "node_type": "concept", "source_page_indices": [6], "keywords": ["red-black", "coloring", "rebalance"]}},
  {{"title": "Graph Algorithms", "description": "Algorithms for traversing and analyzing graph structures.", "depth": 1, "parent_title": null, "node_type": "group", "source_page_indices": [], "keywords": ["graph", "traversal", "shortest path"]}},
  {{"title": "Breadth-First Search", "description": "Level-order graph traversal using a queue.", "depth": 2, "parent_title": "Graph Algorithms", "node_type": "concept", "source_page_indices": [7], "keywords": ["BFS", "queue", "level order"]}}
]}}

Key patterns shown above:
- Depth 1 = ONLY groups (Sorting Algorithms, Tree Data Structures, Graph Algorithms) — never concepts.
- Depth 2 = concepts (Merge Sort, Quick Sort, BST, BFS) or sub-groups (Self-Balancing Trees).
- Depth 3 = concepts under sub-groups (AVL Trees, Red-Black Trees).
- Groups may have empty source_page_indices. Concepts must reference at least one chunk.

--- END EXAMPLE ---

Now extract topics from the provided lecture material. Respond in JSON:
{{"topics": [{{"title": "string", "description": "string", "depth": "integer", "parent_title": "string or null", "node_type": "group or concept", "source_page_indices": ["integer"], "keywords": ["string"]}}]}}"""

DEPENDENCY_INFERENCE_SYSTEM = """You are a curriculum designer. Given a list of topics extracted from lecture material, determine the relationships between them. Every concept node must connect to at least one other node — isolated nodes are not acceptable. Use semantic categories to classify each relationship."""

DEPENDENCY_INFERENCE_USER = """Topics extracted from lecture material:
---
{topics_json}
---

Root node context: {root_context}

Determine the edges between these topics. For each edge, provide:

1. Edge categories — pick the most fitting:
   - "dependency": A must or should be understood before B. A enables, motivates, or is required by B. Directional.
   - "association": A and B are conceptually connected but neither strictly depends on the other. Bidirectional.
   - "hierarchy": A contains B, or B is a specialization/subtopic of A. Structural.

2. Edge label — a short phrase (2-5 words) that reads as "[from_title] [label] [to_title]" along the arrow direction. The label must make a grammatical sentence when read as "A [label] B" where A=from_title, B=to_title. Examples: "is prerequisite for" (A is prerequisite for B), "provides context for", "contrasts with", "contains", "motivates learning of". Be specific.

3. Follow these rules:
   a. EVERY concept node (node_type "concept") MUST have at least one edge — zero exceptions. If no natural dependency exists, create an association edge to its closest sibling or parent. Isolated nodes are a critical failure.
   b. Each topic should have at most 3 incoming dependency edges. Keep only the most critical ones.
   c. Root topics (depth 1) must NOT have incoming dependency edges. They may have association edges between them.
   d. Dependency edges must NOT form cycles.
   e. Cross-depth edges are allowed and encouraged when they reflect real conceptual links.
   f. If a root node is provided at depth 0, create a hierarchy edge from it to every depth-1 group with label "contains". Do NOT create any dependency or association edges to/from the root — only hierarchy edges.
   g. For each edge, provide a brief reasoning (1 sentence) explaining WHY the relationship exists.
   h. Use the exact topic titles from the input. Do not rename or abbreviate them.

Respond in JSON:
{{"edges": [{{"from_title": "string", "to_title": "string", "edge_category": "dependency|association|hierarchy", "edge_label": "string", "reasoning": "string"}}]}}"""

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

ORGANIZE_SYSTEM = """You are a curriculum organizer. Your job is to improve the organizational quality of a knowledge graph extracted from multiple lecture documents. Pay special attention to CROSS-DOCUMENT DUPLICATES — nodes from different source documents that cover the same concept should be merged. Restructure freely for clarity."""

ORGANIZE_USER = """Knowledge graph nodes and their relationships:
---
{graph_json}
---

Each node has:
- node_type ("group" = organizational container, "concept" = teachable unit)
- source_documents: which uploaded documents this node was extracted from
- edges_in/edges_out with categories (dependency, association, hierarchy) and labels

Propose organizational improvements. The goal is a clean, logical hierarchy with no redundancy.

Available suggestion types:
1. MERGE: Two or more nodes that cover the same concept. ACTIVELY look for cross-document duplicates — nodes from different source_documents with similar titles or overlapping subject matter should be merged. Also merge within-document duplicates.
2. SPLIT: One node covering too many distinct concepts.
3. REORDER: Adjust order_index for better pedagogical sequencing.
4. REPARENT: Change parent/depth for better hierarchy placement.
5. CREATE_GROUP: Create a new group node to cluster related concepts. Provide group_title and children list.
6. DISSOLVE_GROUP: Remove a group that adds no value, promoting its children.

Rules:
- PRIORITIZE MERGE for cross-document duplicates. If two nodes from different documents cover the same topic (even with slightly different titles), merge them.
- Be aggressive with all restructuring types.
- Isolated concept nodes (zero edges or only one weak association) are a sign of poor organization — address every one. MERGE into a related node or REPARENT under a relevant group.
- Prefer deeper hierarchy over flat sibling lists. If 5 or more concept nodes sit at the same depth under one parent, CREATE_GROUP to cluster related ones.
- For MERGE: provide both node titles and a merged_title.
- For SPLIT: provide node title and proposed sub-nodes with page references.
- For CREATE_GROUP: provide group_title and children list.
- For DISSOLVE_GROUP: target must be a group node.
- For REORDER: provide node title and new order_index.
- For REPARENT: provide node title and new parent title (or null for depth 1).
- Include reasoning for each suggestion.
- Maximum 40 suggestions.
- The root node (depth 0, node_type "group") is the graph's overall topic. It must ONLY connect to depth-1 groups via hierarchy edges. No concepts should be directly under the root. If any concept sits at depth 1, REPARENT it under an appropriate group or CREATE_GROUP for it.
- Groups should cluster concepts from related documents. Prefer 1-3 source documents per group. If a group covers content from 4+ documents, consider splitting it into smaller thematic groups.
- Do NOT suggest MERGE, SPLIT, REORDER, REPARENT, or DISSOLVE_GROUP for the root node (depth 0).

Respond in JSON:
{{"suggestions": [{{"type": "MERGE|SPLIT|REORDER|REPARENT|CREATE_GROUP|DISSOLVE_GROUP", "node_titles": ["string"], "merged_title": "string or null", "group_title": "string or null", "children": ["string"] or null, "new_parent_title": "string or null", "new_order_index": "integer or null", "split_into": [{{"title": "string", "page_ids": ["string"]}}] or null, "reasoning": "string"}}]}}"""

TOPIC_TITLE_SYSTEM = """You are a curriculum analyst. Given extracted topics from lecture material, generate a concise descriptive title that captures the overall subject matter."""

TOPIC_TITLE_USER = """Course title: {course_title}

Extracted topics:
---
{topics_json}
---

Generate a descriptive topic title (5-10 words) that captures the overall subject matter covered by these topics. This title will be the root node of the knowledge graph. It should be more descriptive than the course title — capturing the specific subjects covered.

Examples:
- Course "CS 101" with topics about sorting, trees, graphs → "Algorithms and Data Structures Fundamentals"
- Course "Physics I" with topics about mechanics, forces, energy → "Classical Mechanics and Newtonian Physics"

Respond in JSON:
{{"topic_title": "string"}}"""


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
