"""Stages 1+2: LLM topic extraction and incremental merge into knowledge graph."""
import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.course import Course
from app.models.node import Node, NodeEdge
from app.models.document import Document, Page, NodePage, Reference
from app.services.llm_client import LLMClient
from app.services.validators import TopicValidator, DependencyValidator, ConnectivityValidator, EmbeddingValidator, MergeValidator, ValidationError
from app.db.vector import upsert_node_embeddings, delete_collection, get_or_create_collection
from app.config import settings

logger = logging.getLogger(__name__)


class GraphBuilder:
    """Stages 1+2: Extract topics from a document's pages and merge into existing graph."""

    def __init__(self, db: Session, openai_api_key: str, model: str = "gpt-4o-mini"):
        self.db = db
        self.api_key = openai_api_key
        self.model = model
        self.llm = LLMClient(api_key=openai_api_key, model=model)

    def run(self, course_id: UUID, document_id: UUID, max_depth: int = 4) -> dict:
        course = self.db.query(Course).filter_by(id=course_id).first()
        if not course:
            raise ValueError(f"Course {course_id} not found")

        document = self.db.query(Document).filter_by(id=document_id, course_id=course_id).first()
        if not document:
            raise ValueError(f"Document {document_id} not found in course {course_id}")
        if document.ingestion_status != "complete":
            raise ValueError(f"Document {document_id} status is '{document.ingestion_status}', expected 'complete'")

        logger.info("[Extract] Starting extraction for doc '%s' (order=%d)", document.title, document.upload_order)

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
        logger.info("[Extract] Stage 1: extracting topics from %d pages...", len(pages))
        topics_response = self.llm.extract_topics(chunks=page_chunks, max_depth=max_depth, course_title=course.title)
        topic_validator = TopicValidator(num_pages=len(pages), max_depth=max_depth)
        topics_response = topic_validator.validate(topics_response)
        raw_topics = topics_response["topics"]
        logger.info("[Extract] Stage 1 complete: %d topics extracted", len(raw_topics))

        # Embedding validation: dedup + persist to ChromaDB
        embedding_validator = EmbeddingValidator(
            api_key=self.api_key,
            course_id=str(course_id),
            threshold=settings.embedding_merge_threshold,
        )

        # Extract references from first document
        is_first_doc = document.upload_order == 1
        if is_first_doc:
            logger.info("[Extract] First doc — extracting references...")
            self._extract_references(course_id, page_chunks)

        # Load existing graph nodes
        existing_nodes = self.db.query(Node).filter_by(course_id=course_id).all()

        has_root = any(n.depth == 0 for n in existing_nodes)
        if not has_root:
            # First document: create all nodes directly (no merge needed)
            logger.info("[Extract] First doc — creating fresh graph...")
            raw_topics = embedding_validator.validate(raw_topics)
            return self._create_fresh_graph(course, raw_topics, page_id_map, pages, max_depth)

        # Stage 2: Add topics from subsequent document (no merge LLM call)
        logger.info("[Extract] Adding topics from doc into existing graph (%d nodes)...", len(existing_nodes))
        existing_titles = {n.title for n in existing_nodes}
        raw_topics = embedding_validator.validate(raw_topics, existing_node_titles=existing_titles)
        return self._add_document_topics(course, existing_nodes, raw_topics, page_id_map, pages, max_depth)

    def _create_fresh_graph(self, course, topics, page_id_map, pages, max_depth):
        """First document: create root node, all topic nodes, edges, and page links."""
        # Root node = course title
        course.topic_title = course.title

        # Create root node at depth 0
        root_node = Node(
            course_id=course.id,
            title=course.title,
            depth=0,
            order_index=0,
            node_type="group",
            parent_ids=[],
            child_ids=[],
        )
        self.db.add(root_node)
        self.db.flush()

        logger.info("[Extract] Created root node '%s' at depth 0", course.title)
        logger.info("[Extract] Creating %d nodes...", len(topics))
        title_to_node = {course.title: root_node}
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
                node_type=topic.get("node_type", "concept"),
                parent_ids=[],
                child_ids=[],
            )
            self.db.add(node)
            self.db.flush()
            title_to_node[topic["title"]] = node

        # Infer edges (pass root_title so LLM creates hierarchy edges)
        logger.info("[Extract] Inferring edges for %d topics...", len(topics))
        topics_for_deps = [
            {"title": t["title"], "description": t["description"],
             "keywords": t["keywords"], "depth": t["depth"]}
            for t in topics
        ]
        edges_response = self.llm.infer_dependencies(topics=topics_for_deps, root_title=course.title)
        dep_validator = DependencyValidator(topics=topics_for_deps)
        edges_response = dep_validator.validate(edges_response)

        # Connectivity validation: auto-connect orphans
        conn_validator = ConnectivityValidator(root_title=course.title)
        topics_for_conn = [{"title": course.title, "depth": 0, "parent_title": None, "node_type": "group"}] + topics_for_deps
        edges_response["edges"] = conn_validator.validate(topics_for_conn, edges_response["edges"])

        edges_created = 0
        seen_pairs = set()
        for edge in edges_response["edges"]:
            from_node = title_to_node.get(edge["from_title"])
            to_node = title_to_node.get(edge["to_title"])
            if from_node and to_node:
                pair = (from_node.id, to_node.id)
                if pair not in seen_pairs:
                    seen_pairs.add(pair)
                    self.db.add(NodeEdge(
                        parent_id=from_node.id,
                        child_id=to_node.id,
                        edge_category=edge["edge_category"],
                        edge_label=edge["edge_label"],
                    ))
                    edges_created += 1
        self.db.flush()

        # Create hierarchy edges from root to all depth-1 nodes (skip if LLM already created one)
        for node in title_to_node.values():
            if node.depth == 1:
                pair = (root_node.id, node.id)
                if pair not in seen_pairs:
                    seen_pairs.add(pair)
                    self.db.add(NodeEdge(
                        parent_id=root_node.id,
                        child_id=node.id,
                        edge_category="hierarchy",
                        edge_label="contains",
                    ))
                    edges_created += 1
        self.db.flush()

        # Update denormalized arrays
        self._update_denormalized_arrays(title_to_node)

        # Re-key node embeddings from title → UUID in ChromaDB
        self._rekey_embeddings(course.id, topics, title_to_node)

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

        logger.info(
            "[Extract] Fresh graph complete: %d nodes, %d edges, %d page links",
            len(title_to_node), edges_created, np_created,
        )
        return {
            "course_id": str(course.id),
            "nodes_created": len(title_to_node),
            "nodes_extended": 0,
            "edges_created": edges_created,
        }

    def _add_document_topics(self, course, existing_nodes, topics, page_id_map, pages, max_depth):
        """Add topics from a subsequent document — no merge LLM call, just create new nodes."""
        root_node = next((n for n in existing_nodes if n.depth == 0), None)
        existing_by_title = {n.title: n for n in existing_nodes}

        # Pre-load existing edge pairs to prevent UniqueViolation on (parent_id, child_id) PK
        existing_edges = (
            self.db.query(NodeEdge.parent_id, NodeEdge.child_id)
            .join(Node, NodeEdge.parent_id == Node.id)
            .filter(Node.course_id == course.id)
            .all()
        )
        seen_pairs = {(e.parent_id, e.child_id) for e in existing_edges}

        logger.info("[Extract] Adding %d topics from new document...", len(topics))
        title_to_node = dict(existing_by_title)
        new_nodes = {}
        order_counters = defaultdict(int)

        for topic in topics:
            # Skip topics that already exist (exact title match)
            if topic["title"] in existing_by_title:
                logger.info("[Extract] Skipping duplicate topic '%s'", topic["title"])
                continue

            parent_key = (topic["depth"], topic.get("parent_title"))
            order_idx = order_counters[parent_key]
            order_counters[parent_key] += 1

            node = Node(
                course_id=course.id,
                title=topic["title"],
                depth=topic["depth"],
                order_index=order_idx,
                node_type=topic.get("node_type", "concept"),
                parent_ids=[],
                child_ids=[],
            )
            self.db.add(node)
            self.db.flush()
            title_to_node[topic["title"]] = node
            new_nodes[topic["title"]] = node

            # Connect depth-1 groups to root
            if node.depth == 1 and root_node:
                pair = (root_node.id, node.id)
                if pair not in seen_pairs:
                    seen_pairs.add(pair)
                    self.db.add(NodeEdge(
                        parent_id=root_node.id,
                        child_id=node.id,
                        edge_category="hierarchy",
                        edge_label="contains",
                    ))

            # Link pages
            for page_idx in topic["source_page_indices"]:
                page_id = page_id_map.get(page_idx)
                if page_id:
                    self.db.add(NodePage(node_id=node.id, page_id=page_id))

        self.db.flush()

        # Infer edges for new nodes
        edges_created = 0
        if new_nodes:
            all_nodes = list(title_to_node.values())
            topics_for_deps = [
                {"title": n.title, "description": "", "keywords": [], "depth": n.depth}
                for n in all_nodes
            ]
            root_title = root_node.title if root_node else None
            edges_response = self.llm.infer_dependencies(topics=topics_for_deps, root_title=root_title)
            dep_validator = DependencyValidator(topics=topics_for_deps)
            edges_response = dep_validator.validate(edges_response)

            conn_validator = ConnectivityValidator(root_title=root_title)
            edges_response["edges"] = conn_validator.validate(topics_for_deps, edges_response["edges"])

            # Only add edges involving new nodes (avoid duplicates with existing edges)
            new_titles = set(new_nodes.keys())
            for edge in edges_response["edges"]:
                if edge["from_title"] in new_titles or edge["to_title"] in new_titles:
                    from_n = title_to_node.get(edge["from_title"])
                    to_n = title_to_node.get(edge["to_title"])
                    if from_n and to_n:
                        pair = (from_n.id, to_n.id)
                        if pair not in seen_pairs:
                            seen_pairs.add(pair)
                            self.db.add(NodeEdge(
                                parent_id=from_n.id,
                                child_id=to_n.id,
                                edge_category=edge["edge_category"],
                                edge_label=edge["edge_label"],
                            ))
                            edges_created += 1
            self.db.flush()

            self._update_denormalized_arrays(title_to_node)

        # Re-key new node embeddings
        new_topics = [t for t in topics if t["title"] in new_nodes]
        if new_topics:
            self._rekey_embeddings(course.id, new_topics, title_to_node)

        course.ingestion_status = "graph_ready"
        self.db.flush()

        logger.info("[Extract] Added %d new nodes, %d edges", len(new_nodes), edges_created)
        return {
            "course_id": str(course.id),
            "nodes_created": len(new_nodes),
            "nodes_extended": 0,
            "edges_created": edges_created,
        }

    def _extract_one(self, doc, pages, course_title, max_depth):
        """Run in thread — LLM extract only, no DB writes."""
        doc_label = f"[doc '{doc.title}' order={doc.upload_order}]"
        logger.info("%s Starting extraction (%d pages)...", doc_label, len(pages))

        llm = LLMClient(api_key=self.api_key, model=self.model)
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

        topics_resp = llm.extract_topics(chunks=page_chunks, max_depth=max_depth, course_title=course_title)
        raw_count = len(topics_resp.get("topics", []))
        logger.info("%s LLM returned %d raw topics, validating...", doc_label, raw_count)

        validator = TopicValidator(num_pages=len(pages), max_depth=max_depth)
        topics_resp = validator.validate(topics_resp)
        valid_count = len(topics_resp["topics"])
        logger.info("%s Validation complete: %d→%d topics", doc_label, raw_count, valid_count)

        return {
            "doc": doc,
            "topics": topics_resp["topics"],
            "page_id_map": page_id_map,
        }

    def build_full_graph(self, course_id: UUID, documents: list, max_depth: int = 4) -> dict:
        """Build graph from all documents with parallel extraction + single dependency inference."""
        course = self.db.query(Course).filter_by(id=course_id).first()
        if not course:
            raise ValueError(f"Course {course_id} not found")

        delete_collection(str(course.id))

        # Load pages for each document (read-only, safe before threading)
        doc_pages = {}
        for doc in documents:
            pages = (
                self.db.query(Page)
                .filter_by(document_id=doc.id)
                .order_by(Page.page_number)
                .all()
            )
            if pages:
                doc_pages[doc.id] = pages

        if not doc_pages:
            raise ValueError("No documents have pages")

        # Phase 1: Parallel extraction
        total_pages = sum(len(p) for p in doc_pages.values())
        doc_summary = ", ".join(f"'{d.title}' ({len(doc_pages.get(d.id, []))}p)" for d in documents if d.id in doc_pages)
        logger.info(
            "[build_full_graph] Phase 1: extracting %d docs (%d total pages) in parallel — %s",
            len(doc_pages), total_pages, doc_summary,
        )
        extractions = []  # ordered by upload_order
        refs_future = None

        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {}
            for doc in documents:
                pages = doc_pages.get(doc.id)
                if not pages:
                    logger.warning("[build_full_graph] Skipping doc '%s' — no pages", doc.title)
                    continue
                fut = pool.submit(self._extract_one, doc, pages, course.title, max_depth)
                futures[fut] = doc

            # Extract references from first document in the same pool
            first_doc = documents[0]
            first_pages = doc_pages.get(first_doc.id)
            if first_pages:
                first_chunks = [
                    {
                        "index": i,
                        "text": p.body,
                        "page_number": p.page_number,
                        "global_page": p.global_page,
                        "heading": p.slide_title,
                    }
                    for i, p in enumerate(first_pages)
                ]

                def _extract_refs(chunks):
                    llm = LLMClient(api_key=self.api_key, model=self.model)
                    return llm.extract_references(chunks)

                refs_future = pool.submit(_extract_refs, first_chunks)
                logger.info("[build_full_graph] Reference extraction submitted for '%s'", first_doc.title)

            for fut in as_completed(futures):
                doc = futures[fut]
                result = fut.result()  # propagate exceptions
                extractions.append(result)
                logger.info(
                    "[build_full_graph] Completed doc '%s': %d topics extracted",
                    doc.title, len(result["topics"]),
                )

        # Sort by upload_order to ensure deterministic dedup (keep first occurrence)
        extractions.sort(key=lambda e: e["doc"].upload_order)
        total_raw_topics = sum(len(e["topics"]) for e in extractions)
        logger.info("[build_full_graph] Phase 1 done: %d docs, %d total raw topics", len(extractions), total_raw_topics)

        # Save references
        if refs_future:
            try:
                refs_response = refs_future.result()
                ref_count = len(refs_response.get("references", []))
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
                logger.info("[build_full_graph] Saved %d references", ref_count)
            except Exception:
                logger.warning("[build_full_graph] Reference extraction failed, continuing without", exc_info=True)

        # Phase 2: Sequential graph construction
        logger.info("[build_full_graph] Phase 2: building graph sequentially...")
        course.topic_title = course.title
        root_node = Node(
            course_id=course.id,
            title=course.title,
            depth=0,
            order_index=0,
            node_type="group",
            parent_ids=[],
            child_ids=[],
        )
        self.db.add(root_node)
        self.db.flush()
        logger.info("[build_full_graph] Created root node '%s' (depth=0)", course.title)

        # Deduplicate topics across documents (keep first occurrence by upload_order)
        seen_titles = {course.title}  # root title already taken
        all_topics = []       # deduplicated topics with their page_id_maps
        title_to_node = {course.title: root_node}
        order_counters = defaultdict(int)
        dupes_skipped = 0

        for extraction in extractions:
            doc_title = extraction["doc"].title
            doc_kept = 0
            for topic in extraction["topics"]:
                if topic["title"] in seen_titles:
                    logger.debug(
                        "[build_full_graph] Dedup: skipping '%s' from doc '%s' (already seen)",
                        topic["title"], doc_title,
                    )
                    dupes_skipped += 1
                    continue
                seen_titles.add(topic["title"])
                doc_kept += 1
                all_topics.append({
                    "topic": topic,
                    "page_id_map": extraction["page_id_map"],
                })
            logger.info("[build_full_graph] Doc '%s': kept %d topics, skipped %d dupes", doc_title, doc_kept, dupes_skipped)

        # Embedding validation on deduplicated topics
        all_topic_dicts = [e["topic"] for e in all_topics]
        embedding_validator = EmbeddingValidator(
            api_key=self.api_key,
            course_id=str(course.id),
            threshold=settings.embedding_merge_threshold,
        )
        cleaned_topics = embedding_validator.validate(all_topic_dicts)
        surviving_titles = {t["title"] for t in cleaned_topics}
        all_topics = [e for e in all_topics if e["topic"]["title"] in surviving_titles]

        logger.info("[build_full_graph] Creating %d unique nodes (%d dupes removed)...", len(all_topics), dupes_skipped)
        for entry in all_topics:
            topic = entry["topic"]
            parent_key = (topic["depth"], topic.get("parent_title"))
            order_idx = order_counters[parent_key]
            order_counters[parent_key] += 1

            node = Node(
                course_id=course.id,
                title=topic["title"],
                depth=topic["depth"],
                order_index=order_idx,
                node_type=topic.get("node_type", "concept"),
                parent_ids=[],
                child_ids=[],
            )
            self.db.add(node)
            self.db.flush()
            title_to_node[topic["title"]] = node

        # Single infer_dependencies call with ALL topics
        topics_for_deps = [
            {"title": e["topic"]["title"], "description": e["topic"]["description"],
             "keywords": e["topic"]["keywords"], "depth": e["topic"]["depth"]}
            for e in all_topics
        ]
        logger.info("[build_full_graph] Inferring edges for %d topics (single LLM call)...", len(topics_for_deps))
        edges_response = self.llm.infer_dependencies(topics=topics_for_deps, root_title=course.title)
        raw_edge_count = len(edges_response.get("edges", []))
        dep_validator = DependencyValidator(topics=topics_for_deps)
        edges_response = dep_validator.validate(edges_response)

        conn_validator = ConnectivityValidator(root_title=course.title)
        topics_for_conn = [{"title": course.title, "depth": 0, "parent_title": None, "node_type": "group"}] + topics_for_deps
        edges_response["edges"] = conn_validator.validate(topics_for_conn, edges_response["edges"])

        logger.info("[build_full_graph] LLM returned %d raw edges, %d after validation", raw_edge_count, len(edges_response["edges"]))

        # Create edges
        edges_created = 0
        seen_pairs = set()
        for edge in edges_response["edges"]:
            from_node = title_to_node.get(edge["from_title"])
            to_node = title_to_node.get(edge["to_title"])
            if from_node and to_node:
                pair = (from_node.id, to_node.id)
                if pair not in seen_pairs:
                    seen_pairs.add(pair)
                    self.db.add(NodeEdge(
                        parent_id=from_node.id,
                        child_id=to_node.id,
                        edge_category=edge["edge_category"],
                        edge_label=edge["edge_label"],
                    ))
                    edges_created += 1
        self.db.flush()

        # Hierarchy edges: root → depth-1 nodes
        for node in title_to_node.values():
            if node.depth == 1:
                pair = (root_node.id, node.id)
                if pair not in seen_pairs:
                    seen_pairs.add(pair)
                    self.db.add(NodeEdge(
                        parent_id=root_node.id,
                        child_id=node.id,
                        edge_category="hierarchy",
                        edge_label="contains",
                    ))
                    edges_created += 1
        self.db.flush()

        # Update denormalized arrays
        self._update_denormalized_arrays(title_to_node)

        # Re-key node embeddings from title → UUID in ChromaDB
        all_topic_objs = [e["topic"] for e in all_topics]
        self._rekey_embeddings(course.id, all_topic_objs, title_to_node)

        # Link pages to nodes
        np_created = 0
        for entry in all_topics:
            topic = entry["topic"]
            page_id_map = entry["page_id_map"]
            node = title_to_node.get(topic["title"])
            if node:
                for page_idx in topic["source_page_indices"]:
                    page_id = page_id_map.get(page_idx)
                    if page_id:
                        self.db.add(NodePage(node_id=node.id, page_id=page_id))
                        np_created += 1
        self.db.flush()

        course.ingestion_status = "graph_ready"
        self.db.flush()

        total_nodes = len(title_to_node)  # includes root
        hierarchy_count = sum(1 for n in title_to_node.values() if n.depth == 1)
        logger.info(
            "[build_full_graph] Done: %d nodes (1 root + %d depth-1 + %d deeper), %d edges, %d page links",
            total_nodes, hierarchy_count, total_nodes - 1 - hierarchy_count, edges_created, np_created,
        )
        return {
            "course_id": str(course.id),
            "docs_extracted": len(extractions),
            "nodes_created": total_nodes,
            "edges_created": edges_created,
        }

    def _rekey_embeddings(self, course_id, topics, title_to_node):
        """Re-key ChromaDB embeddings from title keys to node UUID keys."""
        collection = get_or_create_collection(str(course_id))
        for topic in topics:
            node = title_to_node.get(topic["title"])
            if not node:
                continue
            try:
                result = collection.get(ids=[topic["title"]], include=["embeddings", "metadatas"])
                if len(result["ids"]) > 0 and len(result["embeddings"]) > 0:
                    emb = result["embeddings"][0]
                    meta = result["metadatas"][0] if result["metadatas"] else {}
                    collection.delete(ids=[topic["title"]])
                    collection.upsert(
                        ids=[str(node.id)],
                        embeddings=[emb],
                        metadatas=[{**meta, "title": node.title}],
                    )
            except Exception:
                logger.warning("Failed to re-key embedding for '%s'", topic["title"], exc_info=True)

    def _update_denormalized_arrays(self, title_to_node: dict):
        for node in title_to_node.values():
            parent_edges = (
                self.db.query(NodeEdge)
                .filter_by(child_id=node.id, edge_category="dependency")
                .all()
            )
            child_edges = (
                self.db.query(NodeEdge)
                .filter_by(parent_id=node.id, edge_category="dependency")
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
