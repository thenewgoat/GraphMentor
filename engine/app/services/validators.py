"""Hard and soft validators for LLM outputs with cycle detection and repair."""
import logging
from collections import defaultdict

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
        6. Non-empty page indices: every topic references at least one page
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
            if topic["depth"] == 1:
                if topic["parent_title"] is not None:
                    raise ValidationError(
                        f"Depth-1 topic '{topic['title']}' must have null parent_title"
                    )
            else:
                parent = topic["parent_title"]
                if parent not in title_depths:
                    raise ValidationError(
                        f"Parent '{parent}' not found for topic '{topic['title']}'"
                    )
                if title_depths[parent] >= topic["depth"]:
                    raise ValidationError(
                        f"Parent '{parent}' (depth {title_depths[parent]}) "
                        f"must be shallower than child '{topic['title']}' "
                        f"(depth {topic['depth']})"
                    )

            # 4. Depth cap
            if topic["depth"] > self.max_depth:
                raise ValidationError(
                    f"Topic '{topic['title']}' depth {topic['depth']} "
                    f"exceeds max_depth {self.max_depth}"
                )

            # 5. Page indices valid
            for idx in topic["source_page_indices"]:
                if idx < 0 or idx >= self.num_pages:
                    raise ValidationError(
                        f"Topic '{topic['title']}' references invalid page "
                        f"index {idx} (valid: 0-{self.num_pages - 1})"
                    )

            # 6. Non-empty page indices
            if len(topic["source_page_indices"]) == 0:
                raise ValidationError(
                    f"Topic '{topic['title']}' has empty source_page_indices"
                )

            # 7. Keywords count
            kw = topic.get("keywords", [])
            if len(kw) < 3 or len(kw) > 5:
                raise ValidationError(
                    f"Topic '{topic['title']}' has {len(kw)} keywords "
                    f"(expected 3-5)"
                )

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

    def __init__(self, topics: list[dict]):
        self.valid_titles = {t["title"] for t in topics}
        self.root_titles = {t["title"] for t in topics if t["depth"] == 1}

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

        # 3. Remove self-loops
        before = len(edges)
        edges = [e for e in edges if e["from_title"] != e["to_title"]]
        if len(edges) < before:
            logger.warning(f"Removed {before - len(edges)} self-loop edges")

        # 4. Root topic protection
        before = len(edges)
        edges = [
            e for e in edges
            if not (e["edge_type"] == "prerequisite" and e["to_title"] in self.root_titles)
        ]
        if len(edges) < before:
            logger.warning(f"Removed {before - len(edges)} prerequisite edges targeting root topics")

        # 5. Cycle detection + break
        edges = self._break_cycles(edges)

        # 6. Max 3 prerequisites
        edges = self._enforce_max_prerequisites(edges)

        return {"edges": edges}

    def _break_cycles(self, edges: list[dict]) -> list[dict]:
        """Remove weakest edges until no cycles remain in prerequisite subgraph."""
        prerequisite_edges = [e for e in edges if e["edge_type"] == "prerequisite"]
        other_edges = [e for e in edges if e["edge_type"] != "prerequisite"]

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
        """Keep at most 3 incoming prerequisite edges per topic (strongest reasoning)."""
        from collections import defaultdict

        incoming = defaultdict(list)
        for e in edges:
            if e["edge_type"] == "prerequisite":
                incoming[e["to_title"]].append(e)

        to_remove = []
        for title, prereqs in incoming.items():
            if len(prereqs) > 3:
                prereqs.sort(key=lambda e: len(e["reasoning"]), reverse=True)
                to_remove.extend(prereqs[3:])
                logger.warning(f"Topic '{title}' had {len(prereqs)} prerequisites, trimmed to 3")

        remove_set = {(e["from_title"], e["to_title"]) for e in to_remove}
        return [e for e in edges if (e["from_title"], e["to_title"]) not in remove_set]
