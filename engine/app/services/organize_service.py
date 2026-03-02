import logging
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.node import Node, NodeEdge
from app.models.document import NodePage, Page
from app.services.llm_client import LLMClient

logger = logging.getLogger(__name__)


class OrganizeService:
    """Stage 4: LLM-assisted graph organization suggestions."""

    def __init__(self, db: Session, openai_api_key: str, model: str = "gpt-4o-mini"):
        self.db = db
        self.llm = LLMClient(api_key=openai_api_key, model=model)

    def suggest(self, course_id: UUID) -> list[dict]:
        nodes = self.db.query(Node).filter_by(course_id=course_id).order_by(Node.depth, Node.order_index).all()
        edges = (
            self.db.query(NodeEdge)
            .join(Node, NodeEdge.parent_id == Node.id)
            .filter(Node.course_id == course_id)
            .all()
        )

        # Build graph JSON for LLM
        graph_data = []
        for n in nodes:
            page_ids = [
                str(np.page_id)
                for np in self.db.query(NodePage).filter_by(node_id=n.id).all()
            ]
            graph_data.append({
                "title": n.title,
                "depth": n.depth,
                "order_index": n.order_index,
                "page_ids": page_ids,
                "prerequisites": [
                    str(e.parent_id) for e in edges
                    if e.child_id == n.id and e.edge_type == "prerequisite"
                ],
            })

        response = self.llm.suggest_organization(graph_data)
        suggestions = response.get("suggestions", [])

        # Attach IDs and validate node titles exist
        node_by_title = {n.title: n for n in nodes}
        for i, s in enumerate(suggestions):
            s["id"] = i
            s["valid"] = all(
                t in node_by_title for t in s.get("node_titles", [])
            )

        return [s for s in suggestions if s.get("valid", False)]

    def apply(self, course_id: UUID, suggestion_ids: list[int], suggestions: list[dict]) -> dict:
        """Apply selected organization suggestions."""
        nodes = self.db.query(Node).filter_by(course_id=course_id).all()
        node_by_title = {n.title: n for n in nodes}

        applied = 0
        for s in suggestions:
            if s.get("id") not in suggestion_ids:
                continue

            stype = s["type"].upper()
            if stype == "MERGE":
                applied += self._apply_merge(node_by_title, s)
            elif stype == "SPLIT":
                applied += self._apply_split(course_id, node_by_title, s)
            elif stype == "REORDER":
                applied += self._apply_reorder(node_by_title, s)
            elif stype == "REPARENT":
                applied += self._apply_reparent(node_by_title, s)

        self.db.flush()
        return {"applied": applied}

    def _apply_merge(self, node_by_title, suggestion) -> int:
        titles = suggestion.get("node_titles", [])
        if len(titles) < 2:
            return 0

        merged_title = suggestion.get("merged_title", titles[0])
        keep_node = node_by_title.get(titles[0])
        if not keep_node:
            return 0

        keep_node.title = merged_title

        for title in titles[1:]:
            remove_node = node_by_title.get(title)
            if not remove_node:
                continue
            # Move page references to kept node
            for np in self.db.query(NodePage).filter_by(node_id=remove_node.id).all():
                existing = self.db.query(NodePage).filter_by(
                    node_id=keep_node.id, page_id=np.page_id
                ).first()
                if not existing:
                    self.db.add(NodePage(node_id=keep_node.id, page_id=np.page_id))
            # Move incoming edges to kept node
            for edge in self.db.query(NodeEdge).filter_by(child_id=remove_node.id).all():
                if edge.parent_id != keep_node.id:
                    existing = self.db.get(NodeEdge, (edge.parent_id, keep_node.id))
                    if not existing:
                        self.db.add(NodeEdge(
                            parent_id=edge.parent_id, child_id=keep_node.id, edge_type=edge.edge_type
                        ))
            # Move outgoing edges
            for edge in self.db.query(NodeEdge).filter_by(parent_id=remove_node.id).all():
                if edge.child_id != keep_node.id:
                    existing = self.db.get(NodeEdge, (keep_node.id, edge.child_id))
                    if not existing:
                        self.db.add(NodeEdge(
                            parent_id=keep_node.id, child_id=edge.child_id, edge_type=edge.edge_type
                        ))
            self.db.delete(remove_node)

        self.db.flush()
        node_by_title[merged_title] = keep_node
        return 1

    def _apply_split(self, course_id, node_by_title, suggestion) -> int:
        titles = suggestion.get("node_titles", [])
        if not titles:
            return 0
        source_node = node_by_title.get(titles[0])
        if not source_node:
            return 0

        split_into = suggestion.get("split_into", [])
        if len(split_into) < 2:
            return 0

        for i, sub in enumerate(split_into):
            new_node = Node(
                course_id=course_id,
                title=sub["title"],
                depth=source_node.depth,
                order_index=source_node.order_index + i,
                parent_ids=[],
                child_ids=[],
            )
            self.db.add(new_node)
            self.db.flush()

            for page_id_str in sub.get("page_ids", []):
                from uuid import UUID as UUIDType
                try:
                    pid = UUIDType(page_id_str)
                    self.db.add(NodePage(node_id=new_node.id, page_id=pid))
                except ValueError:
                    pass

            node_by_title[sub["title"]] = new_node

        self.db.delete(source_node)
        self.db.flush()
        return 1

    def _apply_reorder(self, node_by_title, suggestion) -> int:
        titles = suggestion.get("node_titles", [])
        if not titles:
            return 0
        node = node_by_title.get(titles[0])
        if not node:
            return 0
        new_order = suggestion.get("new_order_index")
        if new_order is not None:
            node.order_index = new_order
            return 1
        return 0

    def _apply_reparent(self, node_by_title, suggestion) -> int:
        titles = suggestion.get("node_titles", [])
        if not titles:
            return 0
        node = node_by_title.get(titles[0])
        if not node:
            return 0
        new_parent_title = suggestion.get("new_parent_title")
        if new_parent_title is None:
            node.depth = 1
        else:
            parent = node_by_title.get(new_parent_title)
            if parent:
                node.depth = parent.depth + 1
        return 1
