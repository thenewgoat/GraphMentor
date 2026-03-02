"""Stages 1+2: LLM topic extraction and incremental merge into knowledge graph."""
import logging
from collections import defaultdict
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.course import Course
from app.models.node import Node, NodeEdge
from app.models.document import Document, Page, NodePage, Reference
from app.services.llm_client import LLMClient
from app.services.validators import TopicValidator, DependencyValidator, MergeValidator, ValidationError

logger = logging.getLogger(__name__)


class GraphBuilder:
    """Stages 1+2: Extract topics from a document's pages and merge into existing graph."""

    def __init__(self, db: Session, openai_api_key: str, model: str = "gpt-4o-mini"):
        self.db = db
        self.llm = LLMClient(api_key=openai_api_key, model=model)

    def run(self, course_id: UUID, document_id: UUID, max_depth: int = 3) -> dict:
        course = self.db.query(Course).filter_by(id=course_id).first()
        if not course:
            raise ValueError(f"Course {course_id} not found")

        document = self.db.query(Document).filter_by(id=document_id, course_id=course_id).first()
        if not document:
            raise ValueError(f"Document {document_id} not found in course {course_id}")
        if document.ingestion_status != "complete":
            raise ValueError(f"Document {document_id} status is '{document.ingestion_status}', expected 'complete'")

        # Load pages for this document
        pages = (
            self.db.query(Page)
            .filter_by(document_id=document_id)
            .order_by(Page.page_number)
            .all()
        )
        if not pages:
            raise ValueError(f"Document {document_id} has no pages")

        # Build page chunks for LLM
        page_chunks = [
            {
                "index": i,
                "text": p.body,
                "page_number": p.page_number,
                "global_page": p.global_page,
                "heading": p.slide_title,
            }
            for i, p in enumerate(pages)
        ]
        page_id_map = {i: p.id for i, p in enumerate(pages)}

        # Stage 1: Extract topics from this document's pages
        topics_response = self.llm.extract_topics(chunks=page_chunks, max_depth=max_depth)
        topic_validator = TopicValidator(num_pages=len(pages), max_depth=max_depth)
        topics_response = topic_validator.validate(topics_response)
        raw_topics = topics_response["topics"]

        # Extract references from first document
        is_first_doc = document.upload_order == 1
        if is_first_doc:
            self._extract_references(course_id, page_chunks)

        # Load existing graph nodes
        existing_nodes = self.db.query(Node).filter_by(course_id=course_id).all()

        if not existing_nodes:
            # First document: create all nodes directly (no merge needed)
            return self._create_fresh_graph(course, raw_topics, page_id_map, pages, max_depth)

        # Stage 2: Merge into existing graph
        existing_node_data = [
            {"title": n.title, "depth": n.depth, "description": ""}
            for n in existing_nodes
        ]
        merge_response = self.llm.merge_topics(
            existing_nodes=existing_node_data,
            new_topics=raw_topics,
        )
        merge_validator = MergeValidator(
            existing_titles={n.title for n in existing_nodes},
            num_new_pages=len(pages),
        )
        merge_response = merge_validator.validate(merge_response)

        return self._apply_merge(course, existing_nodes, merge_response["decisions"], raw_topics, page_id_map, pages, max_depth)

    def _create_fresh_graph(self, course, topics, page_id_map, pages, max_depth):
        """First document: create all nodes, edges, and page links."""
        title_to_node = {}
        order_counters = defaultdict(int)

        for topic in topics:
            parent_key = (topic["depth"], topic.get("parent_title"))
            order_idx = order_counters[parent_key]
            order_counters[parent_key] += 1

            node = Node(
                course_id=course.id,
                title=topic["title"],
                depth=topic["depth"],
                order_index=order_idx,
                parent_ids=[],
                child_ids=[],
            )
            self.db.add(node)
            self.db.flush()
            title_to_node[topic["title"]] = node

        # Infer edges
        topics_for_deps = [
            {"title": t["title"], "description": t["description"],
             "keywords": t["keywords"], "depth": t["depth"]}
            for t in topics
        ]
        edges_response = self.llm.infer_dependencies(topics=topics_for_deps)
        dep_validator = DependencyValidator(topics=topics_for_deps)
        edges_response = dep_validator.validate(edges_response)

        edges_created = 0
        for edge in edges_response["edges"]:
            from_node = title_to_node.get(edge["from_title"])
            to_node = title_to_node.get(edge["to_title"])
            if from_node and to_node:
                self.db.add(NodeEdge(
                    parent_id=from_node.id, child_id=to_node.id, edge_type=edge["edge_type"]
                ))
                edges_created += 1
        self.db.flush()

        # Update denormalized arrays
        self._update_denormalized_arrays(title_to_node)

        # Link pages to nodes
        np_created = 0
        for topic in topics:
            node = title_to_node[topic["title"]]
            for page_idx in topic["source_page_indices"]:
                page_id = page_id_map.get(page_idx)
                if page_id:
                    self.db.add(NodePage(node_id=node.id, page_id=page_id))
                    np_created += 1
        self.db.flush()

        course.ingestion_status = "graph_ready"
        self.db.flush()

        return {
            "course_id": str(course.id),
            "nodes_created": len(title_to_node),
            "nodes_extended": 0,
            "edges_created": edges_created,
        }

    def _apply_merge(self, course, existing_nodes, decisions, raw_topics, page_id_map, pages, max_depth):
        """Merge new topics into existing graph based on LLM decisions."""
        existing_by_title = {n.title: n for n in existing_nodes}
        nodes_created = 0
        nodes_extended = 0
        new_nodes = {}
        order_counters = defaultdict(int)

        for decision in decisions:
            action = decision["action"].upper()
            page_indices = decision.get("source_page_indices", [])

            if action == "NEW":
                parent_key = (decision.get("depth", 1), decision.get("parent_title"))
                order_idx = order_counters[parent_key]
                order_counters[parent_key] += 1

                node = Node(
                    course_id=course.id,
                    title=decision["new_title"],
                    depth=decision.get("depth", 1),
                    order_index=order_idx,
                    parent_ids=[],
                    child_ids=[],
                )
                self.db.add(node)
                self.db.flush()
                new_nodes[decision["new_title"]] = node
                nodes_created += 1

                # Link pages
                for pi in page_indices:
                    pid = page_id_map.get(pi)
                    if pid:
                        self.db.add(NodePage(node_id=node.id, page_id=pid))

            elif action == "EXTEND":
                target = existing_by_title.get(decision.get("existing_node_title"))
                if target:
                    for pi in page_indices:
                        pid = page_id_map.get(pi)
                        if pid:
                            existing_link = (
                                self.db.query(NodePage)
                                .filter_by(node_id=target.id, page_id=pid)
                                .first()
                            )
                            if not existing_link:
                                self.db.add(NodePage(node_id=target.id, page_id=pid))
                    nodes_extended += 1

        self.db.flush()

        # Infer edges for new nodes if any were created
        edges_created = 0
        if new_nodes:
            all_nodes = list(existing_by_title.values()) + list(new_nodes.values())
            topics_for_deps = [
                {"title": n.title, "description": "", "keywords": [], "depth": n.depth}
                for n in all_nodes
            ]
            edges_response = self.llm.infer_dependencies(topics=topics_for_deps)
            dep_validator = DependencyValidator(topics=topics_for_deps)
            edges_response = dep_validator.validate(edges_response)

            # Only add edges involving new nodes
            new_titles = set(new_nodes.keys())
            all_by_title = {n.title: n for n in all_nodes}
            for edge in edges_response["edges"]:
                if edge["from_title"] in new_titles or edge["to_title"] in new_titles:
                    from_n = all_by_title.get(edge["from_title"])
                    to_n = all_by_title.get(edge["to_title"])
                    if from_n and to_n:
                        existing_edge = self.db.get(NodeEdge, (from_n.id, to_n.id))
                        if not existing_edge:
                            self.db.add(NodeEdge(
                                parent_id=from_n.id, child_id=to_n.id, edge_type=edge["edge_type"]
                            ))
                            edges_created += 1
            self.db.flush()

            # Update denormalized arrays for all nodes
            all_by_title_map = {**existing_by_title, **new_nodes}
            self._update_denormalized_arrays(all_by_title_map)

        course.ingestion_status = "graph_ready"
        self.db.flush()

        return {
            "course_id": str(course.id),
            "nodes_created": nodes_created,
            "nodes_extended": nodes_extended,
            "edges_created": edges_created,
        }

    def _update_denormalized_arrays(self, title_to_node: dict):
        for node in title_to_node.values():
            parent_edges = (
                self.db.query(NodeEdge)
                .filter_by(child_id=node.id, edge_type="prerequisite")
                .all()
            )
            child_edges = (
                self.db.query(NodeEdge)
                .filter_by(parent_id=node.id, edge_type="prerequisite")
                .all()
            )
            node.parent_ids = [e.parent_id for e in parent_edges]
            node.child_ids = [e.child_id for e in child_edges]
        self.db.flush()

    def _extract_references(self, course_id, page_chunks):
        """Extract references from first document's pages."""
        try:
            refs_response = self.llm.extract_references(page_chunks)
            for ref in refs_response.get("references", []):
                self.db.add(Reference(
                    course_id=course_id,
                    ref_type=ref.get("ref_type", "book"),
                    title=ref["title"],
                    author=ref.get("author"),
                    isbn=ref.get("isbn"),
                    url=ref.get("url"),
                ))
            self.db.flush()
        except Exception:
            logger.warning("Reference extraction failed, continuing without references", exc_info=True)
