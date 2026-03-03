"""Stage 4: LLM-assisted graph reorganization (merge, split, reorder, reparent)."""
import logging
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.node import Node, NodeEdge
from app.models.document import NodePage, Page
from app.db.vector import delete_embeddings
from app.services.llm_client import LLMClient

logger = logging.getLogger(__name__)


class OrganizeService:
    """Stage 4: LLM-assisted graph organization suggestions."""

    def __init__(self, db: Session, openai_api_key: str, model: str = "gpt-4o-mini"):
        self.db = db
        self.llm = LLMClient(api_key=openai_api_key, model=model)

    def suggest(self, course_id: UUID) -> list[dict]:
        logger.info("[Organize] Generating suggestions for course %s", course_id)
        nodes = self.db.query(Node).filter_by(course_id=course_id).order_by(Node.depth, Node.order_index).all()
        edges = (
            self.db.query(NodeEdge)
            .join(Node, NodeEdge.parent_id == Node.id)
            .filter(Node.course_id == course_id)
            .all()
        )

        # Build document source map: node_id → set of document titles
        from app.models.document import Document
        node_doc_rows = (
            self.db.query(NodePage.node_id, Document.title)
            .join(Page, NodePage.page_id == Page.id)
            .join(Document, Page.document_id == Document.id)
            .filter(Page.course_id == course_id)
            .distinct()
            .all()
        )
        node_docs: dict[str, list[str]] = {}
        for nid, dtitle in node_doc_rows:
            node_docs.setdefault(str(nid), [])
            if dtitle not in node_docs[str(nid)]:
                node_docs[str(nid)].append(dtitle)

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
                "node_type": n.node_type,
                "source_documents": node_docs.get(str(n.id), []),
                "page_ids": page_ids,
                "edges_in": [
                    {"from": next((nd.title for nd in nodes if nd.id == e.parent_id), str(e.parent_id)),
                     "category": e.edge_category, "label": e.edge_label}
                    for e in edges if e.child_id == n.id
                ],
                "edges_out": [
                    {"to": next((nd.title for nd in nodes if nd.id == e.child_id), str(e.child_id)),
                     "category": e.edge_category, "label": e.edge_label}
                    for e in edges if e.parent_id == n.id
                ],
            })

        logger.info("[Organize] Sending %d nodes to LLM for analysis...", len(graph_data))
        response = self.llm.suggest_organization(graph_data)
        suggestions = response.get("suggestions", [])

        # Attach IDs and validate node titles exist
        node_by_title = {n.title: n for n in nodes}
        for i, s in enumerate(suggestions):
            s["id"] = i
            s["valid"] = all(
                t in node_by_title for t in s.get("node_titles", [])
            )

        valid = [s for s in suggestions if s.get("valid", False)]
        logger.info("[Organize] %d suggestions returned, %d valid", len(suggestions), len(valid))
        return valid

    def apply(self, course_id: UUID, suggestion_ids: list[int], suggestions: list[dict]) -> dict:
        """Apply selected organization suggestions."""
        nodes = self.db.query(Node).filter_by(course_id=course_id).all()
        node_by_title = {n.title: n for n in nodes}

        merge_count = sum(1 for s in suggestions if s.get("id") in suggestion_ids and s["type"].upper() == "MERGE")
        if merge_count > 2:
            logger.warning(f"Applying {merge_count} MERGE suggestions in one batch — LLM may be over-merging")

        logger.info("[Organize] Applying %d of %d suggestions", len(suggestion_ids), len(suggestions))
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
            elif stype == "CREATE_GROUP":
                applied += self._apply_create_group(course_id, node_by_title, s)
            elif stype == "DISSOLVE_GROUP":
                applied += self._apply_dissolve_group(course_id, node_by_title, s)

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
            with self.db.no_autoflush:
                in_edges = self.db.query(NodeEdge).filter_by(child_id=remove_node.id).all()
                out_edges = self.db.query(NodeEdge).filter_by(parent_id=remove_node.id).all()
                # Verify all referenced nodes still exist
                ref_ids = {e.parent_id for e in in_edges} | {e.child_id for e in out_edges}
                ref_ids.discard(keep_node.id)
                ref_ids.discard(remove_node.id)
                live_ids = set(
                    row[0] for row in
                    self.db.query(Node.id).filter(Node.id.in_(list(ref_ids))).all()
                ) if ref_ids else set()
                live_ids.add(keep_node.id)

            for edge in in_edges:
                if edge.parent_id != keep_node.id and edge.parent_id in live_ids:
                    existing = self.db.get(NodeEdge, (edge.parent_id, keep_node.id))
                    if not existing:
                        self.db.add(NodeEdge(
                            parent_id=edge.parent_id, child_id=keep_node.id,
                            edge_category=edge.edge_category, edge_label=edge.edge_label
                        ))
            # Move outgoing edges
            for edge in out_edges:
                if edge.child_id != keep_node.id and edge.child_id in live_ids:
                    existing = self.db.get(NodeEdge, (keep_node.id, edge.child_id))
                    if not existing:
                        self.db.add(NodeEdge(
                            parent_id=keep_node.id, child_id=edge.child_id,
                            edge_category=edge.edge_category, edge_label=edge.edge_label
                        ))
            self.db.delete(remove_node)
            delete_embeddings(str(remove_node.course_id), [str(remove_node.id)])
            node_by_title.pop(title, None)

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
        delete_embeddings(str(course_id), [str(source_node.id)])
        node_by_title.pop(titles[0], None)
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

    def _apply_create_group(self, course_id, node_by_title, suggestion) -> int:
        """Create a new group node and reparent specified children under it."""
        group_title = suggestion.get("group_title") or suggestion.get("merged_title")
        if not group_title:
            return 0
        children_titles = suggestion.get("children", suggestion.get("node_titles", []))
        if len(children_titles) < 1:
            return 0

        child_nodes = [node_by_title.get(t) for t in children_titles]
        child_nodes = [n for n in child_nodes if n is not None]
        if not child_nodes:
            return 0

        # Verify children still exist in DB (earlier suggestions may have deleted them)
        with self.db.no_autoflush:
            live_ids = set(
                row[0] for row in
                self.db.query(Node.id).filter(Node.id.in_([n.id for n in child_nodes])).all()
            )
        child_nodes = [n for n in child_nodes if n.id in live_ids]
        if not child_nodes:
            return 0

        min_depth = min(n.depth for n in child_nodes)
        group_depth = max(1, min_depth)

        group_node = Node(
            course_id=course_id,
            title=group_title,
            depth=group_depth,
            order_index=min(n.order_index for n in child_nodes),
            node_type="group",
            parent_ids=[],
            child_ids=[],
        )
        self.db.add(group_node)
        self.db.flush()

        for child in child_nodes:
            child.depth = group_depth + 1
            self.db.add(NodeEdge(
                parent_id=group_node.id,
                child_id=child.id,
                edge_category="hierarchy",
                edge_label="contains",
            ))

        self.db.flush()
        node_by_title[group_title] = group_node
        return 1

    def _apply_dissolve_group(self, course_id, node_by_title, suggestion) -> int:
        """Remove a group node, promoting its children to the group's parent level."""
        titles = suggestion.get("node_titles", [])
        if not titles:
            return 0
        group_node = node_by_title.get(titles[0])
        if not group_node or group_node.node_type != "group":
            return 0

        child_edges = (
            self.db.query(NodeEdge)
            .filter_by(parent_id=group_node.id, edge_category="hierarchy")
            .all()
        )
        child_ids = {e.child_id for e in child_edges}
        children = self.db.query(Node).filter(Node.id.in_(child_ids)).all() if child_ids else []

        for child in children:
            child.depth = max(1, child.depth - 1)

        with self.db.no_autoflush:
            group_in_edges = (
                self.db.query(NodeEdge)
                .filter(NodeEdge.child_id == group_node.id, NodeEdge.edge_category != "hierarchy")
                .all()
            )
            group_out_edges = (
                self.db.query(NodeEdge)
                .filter(NodeEdge.parent_id == group_node.id, NodeEdge.edge_category != "hierarchy")
                .all()
            )
            # Collect all referenced node IDs and verify they still exist
            ref_ids = set()
            for e in group_in_edges:
                ref_ids.add(e.parent_id)
            for e in group_out_edges:
                ref_ids.add(e.child_id)
            for c in children:
                ref_ids.add(c.id)
            live_ids = set(
                row[0] for row in
                self.db.query(Node.id).filter(Node.id.in_(list(ref_ids))).all()
            ) if ref_ids else set()

        for child in children:
            if child.id not in live_ids:
                continue
            for edge in group_in_edges:
                if edge.parent_id != child.id and edge.parent_id in live_ids:
                    existing = self.db.get(NodeEdge, (edge.parent_id, child.id))
                    if not existing:
                        self.db.add(NodeEdge(
                            parent_id=edge.parent_id, child_id=child.id,
                            edge_category=edge.edge_category, edge_label=edge.edge_label,
                        ))
            for edge in group_out_edges:
                if edge.child_id != child.id and edge.child_id in live_ids:
                    existing = self.db.get(NodeEdge, (child.id, edge.child_id))
                    if not existing:
                        self.db.add(NodeEdge(
                            parent_id=child.id, child_id=edge.child_id,
                            edge_category=edge.edge_category, edge_label=edge.edge_label,
                        ))

        self.db.delete(group_node)
        delete_embeddings(str(course_id), [str(group_node.id)])
        node_by_title.pop(titles[0], None)
        self.db.flush()
        return 1
