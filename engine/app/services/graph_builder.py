# engine/app/services/graph_builder.py
import logging
from collections import defaultdict
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.course import Course
from app.models.node import Node, NodeEdge
from app.models.sentence import Sentence, NodeSentence
from app.services.chunker import build_chunks_from_sentences
from app.services.llm_client import LLMClient
from app.services.validators import TopicValidator, DependencyValidator, ValidationError

logger = logging.getLogger(__name__)


class GraphBuilder:
    """Orchestrates LLM-based topic extraction and DAG construction."""

    def __init__(self, db: Session, openai_api_key: str, model: str = "gpt-4o-mini"):
        self.db = db
        self.llm = LLMClient(api_key=openai_api_key, model=model)

    def run(self, course_id: UUID, max_depth: int = 3) -> dict:
        # 1. Load course
        course = self.db.query(Course).filter_by(id=course_id).first()
        if not course:
            raise ValueError(f"Course {course_id} not found")

        if course.ingestion_status not in ("complete", "graph_ready"):
            raise ValueError(
                f"Course {course_id} has status '{course.ingestion_status}', expected 'complete' or 'graph_ready'"
            )

        # Idempotency: wipe old nodes if re-running
        existing_nodes = self.db.query(Node).filter_by(course_id=course_id).all()
        if existing_nodes:
            logger.info(f"Re-run: deleting {len(existing_nodes)} existing nodes for course {course_id}")
            existing_node_ids = [n.id for n in existing_nodes]
            # Delete node_sentences first (composite PK prevents ORM cascade)
            self.db.query(NodeSentence).filter(
                NodeSentence.node_id.in_(existing_node_ids)
            ).delete(synchronize_session="fetch")
            # Now delete nodes (NodeEdge cascades via relationship)
            for node in existing_nodes:
                self.db.delete(node)
            self.db.flush()
            course.ingestion_status = "complete"
            self.db.flush()

        # 2. Load sentences and build chunks
        sentences = (
            self.db.query(Sentence)
            .filter_by(course_id=course_id)
            .order_by(Sentence.page, Sentence.position)
            .all()
        )

        if not sentences:
            raise ValueError(f"Course {course_id} has no sentences")

        chunks, chunk_sentence_map = build_chunks_from_sentences(sentences)
        logger.info(f"Built {len(chunks)} chunks from {len(sentences)} sentences")

        # 3. LLM Call 1: Topic extraction
        topics_response = self.llm.extract_topics(chunks=chunks, max_depth=max_depth)

        # 4. Validate topics
        topic_validator = TopicValidator(num_chunks=len(chunks), max_depth=max_depth)
        topics_response = topic_validator.validate(topics_response)
        topics = topics_response["topics"]

        # 5. Stage 1: Create Node rows
        title_to_node = {}
        order_counters = defaultdict(int)

        for topic in topics:
            parent_key = (topic["depth"], topic.get("parent_title"))
            order_idx = order_counters[parent_key]
            order_counters[parent_key] += 1

            node = Node(
                course_id=course_id,
                title=topic["title"],
                depth=topic["depth"],
                order_index=order_idx,
                content_chunk_ids=[],
                parent_ids=[],
                child_ids=[],
            )
            self.db.add(node)
            self.db.flush()
            title_to_node[topic["title"]] = node

        logger.info(f"Created {len(title_to_node)} nodes")

        # 6. LLM Call 2: Dependency inference
        topics_for_deps = [
            {"title": t["title"], "description": t["description"],
             "keywords": t["keywords"], "depth": t["depth"]}
            for t in topics
        ]
        edges_response = self.llm.infer_dependencies(topics=topics_for_deps)

        # 7. Validate and repair edges
        dep_validator = DependencyValidator(topics=topics_for_deps)
        edges_response = dep_validator.validate(edges_response)
        edges = edges_response["edges"]

        # 8. Stage 2: Create NodeEdge rows
        edges_created = 0
        for edge in edges:
            from_node = title_to_node.get(edge["from_title"])
            to_node = title_to_node.get(edge["to_title"])
            if from_node and to_node:
                node_edge = NodeEdge(
                    parent_id=from_node.id,
                    child_id=to_node.id,
                    edge_type=edge["edge_type"],
                )
                self.db.add(node_edge)
                edges_created += 1
        self.db.flush()

        # 9. Update denormalized arrays
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

        # 10. Populate node_sentences and content_chunk_ids
        ns_created = 0
        for topic in topics:
            node = title_to_node[topic["title"]]
            sentence_ids = []
            for chunk_idx in topic["source_chunk_indices"]:
                sentence_ids.extend(chunk_sentence_map[chunk_idx])

            for sid in sentence_ids:
                ns = NodeSentence(node_id=node.id, sentence_id=sid)
                self.db.add(ns)
                ns_created += 1

            node.content_chunk_ids = [str(sid) for sid in sentence_ids]
        self.db.flush()

        # 11. Update course status
        course.ingestion_status = "graph_ready"
        self.db.flush()

        logger.info(f"Graph built: {len(title_to_node)} nodes, {edges_created} edges, {ns_created} node_sentences")

        return {
            "course_id": str(course_id),
            "nodes_created": len(title_to_node),
            "edges_created": edges_created,
            "node_sentences_created": ns_created,
        }
