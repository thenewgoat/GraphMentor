"""Hard and soft validators for LLM outputs with cycle detection and repair."""
import logging
from collections import defaultdict

import numpy as np

from app.db.vector import query_similar, upsert_node_embeddings
from app.services.embedder import OpenAIEmbedder

logger = logging.getLogger(__name__)


class ValidationError(Exception):
    """Raised when LLM output fails hard validation."""
    pass


class TopicValidator:
    """Validates topic extraction LLM output (9 checks).

    Hard checks (raise ValidationError):
        1. Structure: response contains 'topics' list with >= 1 entry
        2. Unique titles: no duplicate topic titles
        3. Parent references: parent_title exists and is shallower
        4. Depth cap: no topic exceeds max_depth
        5. Page indices valid: all indices in [0, num_pages)
        6. Non-empty page indices: concept topics must reference at least one page (groups may be empty)
        7. Keywords count: each topic has 3-5 keywords

    Soft checks (log warnings):
        8. Broad topics: warns if a topic covers > 40% of pages
        9. Single-child parents: warns if a parent has only 1 child
    """

    def __init__(self, num_pages: int, max_depth: int):
        self.num_pages = num_pages
        self.max_depth = max_depth

    def validate(self, data: dict) -> dict:
        # 1. Structure check
        if "topics" not in data or not isinstance(data["topics"], list):
            raise ValidationError("Response missing 'topics' array")

        topics = data["topics"]
        if len(topics) == 0:
            raise ValidationError("No topics extracted")

        titles = [t["title"] for t in topics]
        title_depths = {t["title"]: t["depth"] for t in topics}

        # 2. Unique titles
        if len(titles) != len(set(titles)):
            dupes = [t for t in titles if titles.count(t) > 1]
            raise ValidationError(f"Duplicate titles: {set(dupes)}")

        for topic in topics:
            # 3. Parent references
            if topic["parent_title"] is None:
                if topic["depth"] != 1:
                    raise ValidationError(
                        f"Topic '{topic['title']}' has no parent but depth {topic['depth']} != 1"
                    )
            else:
                parent = topic["parent_title"]
                if parent not in title_depths:
                    raise ValidationError(
                        f"Parent '{parent}' not found for topic '{topic['title']}'"
                    )
                if title_depths[parent] >= topic["depth"]:
                    corrected = title_depths[parent] + 1
                    logger.warning(
                        "Auto-correcting depth of '%s' from %d to %d "
                        "(parent '%s' is at depth %d)",
                        topic["title"], topic["depth"], corrected,
                        parent, title_depths[parent],
                    )
                    topic["depth"] = corrected
                    title_depths[topic["title"]] = corrected

            # 4. Depth cap — clamp to max_depth instead of failing
            if topic["depth"] > self.max_depth:
                logger.warning(
                    "Clamping depth of '%s' from %d to %d (max_depth)",
                    topic["title"], topic["depth"], self.max_depth,
                )
                topic["depth"] = self.max_depth
                title_depths[topic["title"]] = self.max_depth

            # 5. Default node_type (before page-index check which depends on it)
            if "node_type" not in topic:
                topic["node_type"] = "concept"
            elif topic["node_type"] not in ("concept", "group"):
                topic["node_type"] = "concept"

            # 5b. Depth-1 nodes must be groups (containers under root)
            if topic["depth"] == 1 and topic["node_type"] != "group":
                logger.warning(
                    "Forcing depth-1 topic '%s' to group (was concept)",
                    topic["title"],
                )
                topic["node_type"] = "group"

            # 6. Page indices valid
            for idx in topic["source_page_indices"]:
                if idx < 0 or idx >= self.num_pages:
                    raise ValidationError(
                        f"Topic '{topic['title']}' references invalid page "
                        f"index {idx} (valid: 0-{self.num_pages - 1})"
                    )

            # 7. Non-empty page indices (groups may have empty lists)
            if len(topic["source_page_indices"]) == 0 and topic["node_type"] != "group":
                logger.warning(
                    "Dropping concept topic '%s' — empty source_page_indices",
                    topic["title"],
                )
                topic["_drop"] = True

            # 8. Keywords count (soft — warn only, don't crash pipeline)
            kw = topic.get("keywords", [])
            if not kw:
                topic["keywords"] = [topic["title"].split()[0], "topic", "concept"]
                logger.warning("Topic '%s' has no keywords — auto-filled defaults", topic["title"])
            elif len(kw) > 5:
                topic["keywords"] = kw[:5]

        # Filter out dropped topics
        dropped = {t["title"] for t in topics if t.get("_drop")}
        if dropped:
            topics = [t for t in topics if not t.get("_drop")]
            # Reparent orphans whose parent was dropped
            for topic in topics:
                if topic.get("parent_title") in dropped:
                    logger.warning(
                        "Reparenting '%s' to depth 1 — parent '%s' was dropped",
                        topic["title"], topic["parent_title"],
                    )
                    topic["parent_title"] = None
                    topic["depth"] = 1
                    topic["node_type"] = "group"
            data["topics"] = topics

        if len(topics) == 0:
            raise ValidationError("No topics remaining after dropping empty concepts")

        # 8. Warn: broad topics
        for topic in topics:
            coverage = len(topic["source_page_indices"]) / self.num_pages
            if coverage > 0.4:
                logger.warning(
                    "Topic '%s' covers %.0f%% of pages — consider splitting",
                    topic["title"],
                    coverage * 100,
                )

        # 9. Warn: single-child parents
        children_per_parent: dict[str, int] = defaultdict(int)
        for topic in topics:
            if topic["parent_title"]:
                children_per_parent[topic["parent_title"]] += 1
        for parent, count in children_per_parent.items():
            if count == 1:
                logger.warning(
                    "Topic '%s' has only 1 child — consider merging or splitting",
                    parent,
                )

        return data


class MergeValidator:
    """Validates merge decisions from LLM."""

    def __init__(self, existing_titles: set[str], num_new_pages: int):
        self.existing_titles = existing_titles
        self.num_new_pages = num_new_pages

    def validate(self, data: dict) -> dict:
        if "decisions" not in data:
            raise ValidationError("Response missing 'decisions' array")

        valid = []
        for d in data["decisions"]:
            action = d.get("action", "").upper()
            if action not in ("NEW", "EXTEND", "SKIP"):
                logger.warning(f"Unknown action '{action}', skipping")
                continue
            if action == "EXTEND" and d.get("existing_node_title") not in self.existing_titles:
                logger.warning(f"EXTEND references unknown node '{d.get('existing_node_title')}', converting to NEW")
                d["action"] = "NEW"
            valid.append(d)

        return {"decisions": valid}


class DependencyValidator:
    """Validates dependency inference LLM output (6 checks, repair-oriented)."""

    VALID_CATEGORIES = {"dependency", "association", "hierarchy"}

    def __init__(self, topics: list[dict]):
        self.valid_titles = {t["title"] for t in topics}
        self.root_titles = {t["title"] for t in topics if t["depth"] <= 1}

    def validate(self, data: dict) -> dict:
        # 1. Structure check
        if "edges" not in data or not isinstance(data["edges"], list):
            raise ValidationError("Response missing 'edges' array")

        edges = data["edges"]

        # 2. Remove unknown titles
        before = len(edges)
        edges = [
            e for e in edges
            if e["from_title"] in self.valid_titles and e["to_title"] in self.valid_titles
        ]
        if len(edges) < before:
            logger.warning(f"Removed {before - len(edges)} edges with unknown titles")

        # Filter invalid categories
        before = len(edges)
        edges = [e for e in edges if e.get("edge_category") in self.VALID_CATEGORIES]
        if len(edges) < before:
            logger.warning(f"Removed {before - len(edges)} edges with invalid categories")

        # Truncate long labels, default empty
        for e in edges:
            if len(e.get("edge_label", "")) > 100:
                e["edge_label"] = e["edge_label"][:100]
            if not e.get("edge_label"):
                e["edge_label"] = "related"

        # 3. Remove self-loops
        before = len(edges)
        edges = [e for e in edges if e["from_title"] != e["to_title"]]
        if len(edges) < before:
            logger.warning(f"Removed {before - len(edges)} self-loop edges")

        # 4. Root topic protection
        before = len(edges)
        edges = [
            e for e in edges
            if not (e["edge_category"] == "dependency" and e["to_title"] in self.root_titles)
        ]
        if len(edges) < before:
            logger.warning(f"Removed {before - len(edges)} dependency edges targeting root topics")

        # 5. Cycle detection + break
        edges = self._break_cycles(edges)

        # 6. Max 3 prerequisites
        edges = self._enforce_max_prerequisites(edges)

        return {"edges": edges}

    def _break_cycles(self, edges: list[dict]) -> list[dict]:
        """Remove weakest edges until no cycles remain in prerequisite subgraph."""
        prerequisite_edges = [e for e in edges if e["edge_category"] == "dependency"]
        other_edges = [e for e in edges if e["edge_category"] != "dependency"]

        while True:
            cycle_edge = self._find_cycle_edge(prerequisite_edges)
            if cycle_edge is None:
                break
            weakest = min(cycle_edge, key=lambda e: len(e["reasoning"]))
            prerequisite_edges.remove(weakest)
            logger.warning(f"Broke cycle by removing edge: {weakest['from_title']} -> {weakest['to_title']}")

        return prerequisite_edges + other_edges

    def _find_cycle_edge(self, edges: list[dict]) -> list[dict] | None:
        """Return edges forming a cycle, or None if DAG is valid. Uses DFS."""
        from collections import defaultdict

        adj = defaultdict(list)
        edge_lookup = {}
        for e in edges:
            adj[e["from_title"]].append(e["to_title"])
            edge_lookup[(e["from_title"], e["to_title"])] = e

        WHITE, GRAY, BLACK = 0, 1, 2
        color = {node: WHITE for node in adj}
        for e in edges:
            if e["to_title"] not in color:
                color[e["to_title"]] = WHITE

        parent = {}

        def dfs(u):
            color[u] = GRAY
            for v in adj.get(u, []):
                if color.get(v, WHITE) == GRAY:
                    cycle_edges = [edge_lookup[(u, v)]]
                    node = u
                    while node != v:
                        p = parent.get(node)
                        if p is None:
                            break
                        if (p, node) in edge_lookup:
                            cycle_edges.append(edge_lookup[(p, node)])
                        node = p
                    return cycle_edges
                if color.get(v, WHITE) == WHITE:
                    parent[v] = u
                    result = dfs(v)
                    if result:
                        return result
            color[u] = BLACK
            return None

        for node in list(color.keys()):
            if color[node] == WHITE:
                result = dfs(node)
                if result:
                    return result
        return None

    def _enforce_max_prerequisites(self, edges: list[dict]) -> list[dict]:
        """Keep at most 3 incoming dependency edges per topic (strongest reasoning)."""
        from collections import defaultdict

        incoming = defaultdict(list)
        for e in edges:
            if e["edge_category"] == "dependency":
                incoming[e["to_title"]].append(e)

        to_remove = []
        for title, prereqs in incoming.items():
            if len(prereqs) > 3:
                prereqs.sort(key=lambda e: len(e["reasoning"]), reverse=True)
                to_remove.extend(prereqs[3:])
                logger.warning(f"Topic '{title}' had {len(prereqs)} prerequisites, trimmed to 3")

        remove_set = {(e["from_title"], e["to_title"]) for e in to_remove}
        return [e for e in edges if (e["from_title"], e["to_title"]) not in remove_set]


class EmbeddingValidator:
    """Deduplicates topics via embedding cosine similarity and persists vectors to ChromaDB.

    Runs after TopicValidator, before node creation. Auto-merges near-duplicate
    topics, optionally deduplicates against existing nodes, warns on over-broad
    nodes, and persists embeddings for downstream retrieval.
    """

    def __init__(self, api_key: str, course_id: str, threshold: float = 0.85):
        self.embedder = OpenAIEmbedder(api_key=api_key)
        self.course_id = course_id
        self.threshold = threshold

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate(
        self,
        topics: list[dict],
        existing_node_titles: set[str] | None = None,
    ) -> list[dict]:
        """Deduplicate *topics* by embedding similarity, persist vectors, return survivors."""
        if not topics:
            return topics

        # 1. Build embedding texts and get vectors in one batch
        texts = [self._embedding_text(t) for t in topics]
        embeddings = self.embedder.get_embeddings(texts)

        # 2. Pairwise cosine similarity → auto-merge above threshold
        topics, embeddings = self._merge_similar(topics, embeddings)

        # 3. Multi-doc dedup against existing nodes in ChromaDB
        if existing_node_titles:
            topics, embeddings = self._dedup_against_existing(
                topics, embeddings, existing_node_titles
            )

        # 4. Flag over-broad nodes (soft warning)
        self._warn_overbroad(topics, embeddings)

        # 5. Persist surviving embeddings to ChromaDB
        if topics:
            node_ids = [t["title"] for t in topics]
            metadatas = [{"title": t["title"]} for t in topics]
            upsert_node_embeddings(
                self.course_id,
                node_ids=node_ids,
                embeddings=embeddings,
                metadatas=metadatas,
            )

        return topics

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _embedding_text(topic: dict) -> str:
        """Build the text blob that gets embedded for a single topic."""
        title = topic.get("title", "")
        description = topic.get("description", "")
        keywords = ", ".join(topic.get("keywords", []))
        return f"{title}. {description}. Keywords: {keywords}"

    def _merge_similar(
        self,
        topics: list[dict],
        embeddings: list[list[float]],
    ) -> tuple[list[dict], list[list[float]]]:
        """Auto-merge topic pairs whose cosine similarity exceeds *self.threshold*.

        The topic appearing first in the list is kept.  Page indices, children,
        and embeddings of the dropped topic transfer to the keeper.
        """
        vecs = np.array(embeddings)
        # Normalize for cosine similarity via dot product
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1, norms)
        normed = vecs / norms
        sim_matrix = normed @ normed.T

        dropped_indices: set[int] = set()
        # Map from dropped title → keeper title (for reparenting)
        merged_into: dict[str, str] = {}

        n = len(topics)
        for i in range(n):
            if i in dropped_indices:
                continue
            for j in range(i + 1, n):
                if j in dropped_indices:
                    continue
                score = float(sim_matrix[i, j])
                if score >= self.threshold:
                    keeper = topics[i]
                    dropped = topics[j]
                    # Transfer page indices
                    combined = sorted(
                        set(keeper["source_page_indices"])
                        | set(dropped["source_page_indices"])
                    )
                    keeper["source_page_indices"] = combined
                    merged_into[dropped["title"]] = keeper["title"]
                    dropped_indices.add(j)
                    logger.warning(
                        "Merged '%s' into '%s' (similarity=%.2f)",
                        dropped["title"],
                        keeper["title"],
                        score,
                    )

        # Reparent children of dropped topics to their keeper
        surviving_topics = []
        surviving_embeddings = []
        for idx, topic in enumerate(topics):
            if idx in dropped_indices:
                continue
            # Reparent: if this topic's parent was merged away, point to keeper
            parent = topic.get("parent_title")
            if parent in merged_into:
                topic["parent_title"] = merged_into[parent]
            surviving_topics.append(topic)
            surviving_embeddings.append(embeddings[idx])

        return surviving_topics, surviving_embeddings

    def _dedup_against_existing(
        self,
        topics: list[dict],
        embeddings: list[list[float]],
        existing_node_titles: set[str],
    ) -> tuple[list[dict], list[list[float]]]:
        """Drop new topics that are near-duplicates of existing ChromaDB nodes."""
        result = query_similar(
            self.course_id,
            query_embeddings=embeddings,
            n_results=1,
        )

        drop_indices: set[int] = set()
        for idx in range(len(topics)):
            if not result["ids"] or idx >= len(result["ids"]):
                continue
            ids_for_query = result["ids"][idx]
            dists_for_query = result["distances"][idx]
            if not ids_for_query:
                continue
            # ChromaDB returns L2 distance by default.
            # For normalised vectors: cosine_sim = 1 - (L2^2 / 2)
            l2_dist = dists_for_query[0]
            cosine_sim = 1.0 - (l2_dist / 2.0)
            matched_id = ids_for_query[0]
            if cosine_sim >= self.threshold and matched_id in existing_node_titles:
                logger.warning(
                    "Dropping new topic '%s' — matches existing node '%s' "
                    "(similarity=%.2f)",
                    topics[idx]["title"],
                    matched_id,
                    cosine_sim,
                )
                drop_indices.add(idx)

        surviving_topics = [t for i, t in enumerate(topics) if i not in drop_indices]
        surviving_embeddings = [e for i, e in enumerate(embeddings) if i not in drop_indices]
        return surviving_topics, surviving_embeddings

    def _warn_overbroad(
        self,
        topics: list[dict],
        embeddings: list[list[float]],
    ) -> None:
        """Log a soft warning when a topic embedding is very close to the centroid."""
        if len(embeddings) < 2:
            return
        vecs = np.array(embeddings)
        centroid = vecs.mean(axis=0)

        c_norm = np.linalg.norm(centroid)
        if c_norm == 0:
            return
        centroid_normed = centroid / c_norm

        for idx, vec in enumerate(vecs):
            v_norm = np.linalg.norm(vec)
            if v_norm == 0:
                continue
            cos = float(np.dot(vec / v_norm, centroid_normed))
            if cos > 0.95:
                logger.warning(
                    "Topic '%s' may be over-broad (centroid similarity=%.3f)",
                    topics[idx]["title"],
                    cos,
                )


class ConnectivityValidator:
    """Ensures every node has at least one edge, auto-connecting orphans.

    Runs after DependencyValidator, before edges are created in DB.
    Orphans are connected via hierarchy edges to their parent, the first
    depth-1 group, or the root node as a fallback.
    """

    def __init__(self, root_title: str | None):
        self.root_title = root_title

    def validate(self, topics: list[dict], edges: list[dict]) -> list[dict]:
        """Return *edges* with auto-generated hierarchy edges for orphan topics."""
        # 1. Build adjacency set — track which titles appear in ANY edge
        connected: set[str] = set()
        for e in edges:
            connected.add(e["from_title"])
            connected.add(e["to_title"])

        # 2. Find orphans — topics with zero edge references (skip root)
        orphans = [
            t for t in topics
            if t["title"] not in connected and t["title"] != self.root_title
        ]

        if not orphans:
            return edges

        # Precompute first depth-1 group (by position in topics list)
        first_group = next(
            (t["title"] for t in topics if t["depth"] == 1 and t["title"] != self.root_title),
            None,
        )

        # 3. Auto-connect each orphan
        new_edges = list(edges)
        for orphan in orphans:
            target = self._find_target(orphan, first_group)
            new_edge = {
                "from_title": target,
                "to_title": orphan["title"],
                "edge_category": "hierarchy",
                "edge_label": "contains",
                "reasoning": "Auto-connected orphan node.",
            }
            new_edges.append(new_edge)
            logger.warning(
                "Auto-connected orphan '%s' to '%s' via hierarchy edge",
                orphan["title"],
                target,
            )

        return new_edges

    def _find_target(self, orphan: dict, first_group: str | None) -> str:
        """Determine which node an orphan should connect to."""
        # If orphan has parent_title set, use it
        if orphan.get("parent_title"):
            return orphan["parent_title"]

        # If no parent_title but depth > 1, connect to first depth-1 group
        if orphan["depth"] > 1:
            if first_group is not None:
                return first_group
            # Fallback: try root
            if self.root_title is not None:
                return self.root_title
            raise ValidationError(
                f"Cannot auto-connect orphan '{orphan['title']}': "
                f"no parent_title, no depth-1 group, and no root node available"
            )

        # depth <= 1: connect to root
        if self.root_title is not None:
            return self.root_title
        raise ValidationError(
            f"Cannot auto-connect orphan '{orphan['title']}': "
            f"no root node available"
        )
