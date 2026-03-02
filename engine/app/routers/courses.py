"""CRUD endpoints for courses, nodes, edges, documents, and references."""
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.postgres import get_db
from app.db.vector import delete_embeddings
from app.models.course import Course
from app.models.node import Node, NodeEdge
from app.models.document import Document, Page, NodePage, Reference


class CreateNodeRequest(BaseModel):
    title: str


class UpdateNodeRequest(BaseModel):
    title: str | None = None
    depth: int | None = None
    order_index: int | None = None


class CreateEdgeRequest(BaseModel):
    parent_id: str
    child_id: str
    edge_type: str = "prerequisite"


class CreateReferenceRequest(BaseModel):
    ref_type: str
    title: str
    author: str | None = None
    isbn: str | None = None
    url: str | None = None


router = APIRouter(prefix="/courses", tags=["courses"])


def _course_to_dict(course: Course, doc_count: int = 0) -> dict:
    return {
        "id": str(course.id),
        "title": course.title,
        "description": course.description,
        "mastery_threshold": course.mastery_threshold,
        "time_decay_lambda": course.time_decay_lambda,
        "max_follow_ups_per_session": course.max_follow_ups_per_session,
        "topic_radius": course.topic_radius,
        "ingestion_status": course.ingestion_status,
        "document_count": doc_count,
        "created_at": course.created_at.isoformat() if course.created_at else None,
        "updated_at": course.updated_at.isoformat() if course.updated_at else None,
    }


@router.get("")
def list_courses(db: Session = Depends(get_db)):
    courses = db.query(Course).order_by(Course.created_at.desc()).all()
    doc_counts = dict(
        db.query(Document.course_id, func.count(Document.id))
        .group_by(Document.course_id)
        .all()
    )
    return [_course_to_dict(c, doc_counts.get(c.id, 0)) for c in courses]


def _node_to_dict(node: Node, pages: list[dict]) -> dict:
    return {
        "id": str(node.id),
        "course_id": str(node.course_id),
        "title": node.title,
        "parent_ids": [str(p) for p in (node.parent_ids or [])],
        "child_ids": [str(c) for c in (node.child_ids or [])],
        "depth": node.depth,
        "order_index": node.order_index,
        "application_examples": node.application_examples,
        "supplementary_content": node.supplementary_content,
        "pages": pages,
    }


def _edge_to_dict(edge: NodeEdge) -> dict:
    return {
        "parent_id": str(edge.parent_id),
        "child_id": str(edge.child_id),
        "edge_type": edge.edge_type,
    }


@router.get("/{course_id}/graph")
def get_graph(course_id: UUID, db: Session = Depends(get_db)):
    course = db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    nodes = db.query(Node).filter(Node.course_id == course_id).order_by(Node.depth, Node.order_index).all()
    edges = (
        db.query(NodeEdge)
        .join(Node, NodeEdge.parent_id == Node.id)
        .filter(Node.course_id == course_id)
        .all()
    )

    # Batch-load pages per node
    node_ids = [n.id for n in nodes]
    node_page_rows = (
        db.query(NodePage.node_id, Page, Document.title.label("doc_title"))
        .join(Page, NodePage.page_id == Page.id)
        .join(Document, Page.document_id == Document.id)
        .filter(NodePage.node_id.in_(node_ids))
        .order_by(Page.global_page)
        .all()
    ) if node_ids else []

    pages_by_node: dict[str, list[dict]] = {}
    for node_id, page, doc_title in node_page_rows:
        key = str(node_id)
        pages_by_node.setdefault(key, []).append({
            "id": str(page.id),
            "page_number": page.page_number,
            "global_page": page.global_page,
            "slide_title": page.slide_title,
            "body": page.body,
            "document_title": doc_title,
        })

    return {
        "nodes": [_node_to_dict(n, pages_by_node.get(str(n.id), [])) for n in nodes],
        "edges": [_edge_to_dict(e) for e in edges],
    }


@router.get("/{course_id}")
def get_course(course_id: UUID, db: Session = Depends(get_db)):
    course = db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    doc_count = db.query(func.count(Document.id)).filter_by(course_id=course_id).scalar()
    return _course_to_dict(course, doc_count or 0)


# --- Documents ---


@router.get("/{course_id}/documents")
def list_documents(course_id: UUID, db: Session = Depends(get_db)):
    course = db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    docs = (
        db.query(Document)
        .filter_by(course_id=course_id)
        .order_by(Document.upload_order)
        .all()
    )
    return [
        {
            "id": str(d.id),
            "title": d.title,
            "filename": d.filename,
            "upload_order": d.upload_order,
            "page_count": d.page_count,
            "ingestion_status": d.ingestion_status,
            "created_at": d.created_at.isoformat() if d.created_at else None,
        }
        for d in docs
    ]


@router.delete("/{course_id}/documents/{doc_id}", status_code=204)
def delete_document(course_id: UUID, doc_id: UUID, db: Session = Depends(get_db)):
    doc = db.get(Document, doc_id)
    if not doc or doc.course_id != course_id:
        raise HTTPException(status_code=404, detail="Document not found")

    # Collect page IDs for embedding cleanup
    page_ids = [str(p.id) for p in doc.pages]

    # Delete embeddings from ChromaDB
    delete_embeddings(course_id=str(course_id), page_ids=page_ids)

    # Delete PDF from disk
    if doc.file_path:
        file_path = Path(doc.file_path)
        if file_path.exists():
            file_path.unlink()

    # Delete document (CASCADE handles pages → node_pages)
    db.delete(doc)
    db.flush()

    # Delete orphan nodes (nodes with zero remaining page links in this course)
    orphan_nodes = (
        db.query(Node)
        .filter(Node.course_id == course_id)
        .outerjoin(NodePage, Node.id == NodePage.node_id)
        .group_by(Node.id)
        .having(func.count(NodePage.page_id) == 0)
        .all()
    )
    for node in orphan_nodes:
        db.delete(node)

    db.flush()
    db.commit()


# --- References ---


@router.get("/{course_id}/references")
def list_references(course_id: UUID, db: Session = Depends(get_db)):
    course = db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    refs = db.query(Reference).filter_by(course_id=course_id).all()
    return [
        {
            "id": str(r.id),
            "ref_type": r.ref_type,
            "title": r.title,
            "author": r.author,
            "isbn": r.isbn,
            "url": r.url,
        }
        for r in refs
    ]


@router.post("/{course_id}/references", status_code=201)
def create_reference(course_id: UUID, body: CreateReferenceRequest, db: Session = Depends(get_db)):
    course = db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    ref = Reference(
        course_id=course_id,
        ref_type=body.ref_type,
        title=body.title,
        author=body.author,
        isbn=body.isbn,
        url=body.url,
    )
    db.add(ref)
    db.flush()
    db.commit()
    return {"id": str(ref.id), "title": ref.title, "ref_type": ref.ref_type}


@router.delete("/{course_id}/references/{ref_id}", status_code=204)
def delete_reference(course_id: UUID, ref_id: UUID, db: Session = Depends(get_db)):
    ref = db.get(Reference, ref_id)
    if not ref or ref.course_id != course_id:
        raise HTTPException(status_code=404, detail="Reference not found")
    db.delete(ref)
    db.flush()
    db.commit()


# --- Node CRUD ---


@router.post("/{course_id}/nodes", status_code=201)
def create_node(course_id: UUID, body: CreateNodeRequest, db: Session = Depends(get_db)):
    course = db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    node = Node(course_id=course_id, title=body.title, depth=0, order_index=0)
    db.add(node)
    db.flush()
    db.commit()
    return _node_to_dict(node, [])


@router.patch("/{course_id}/nodes/{node_id}")
def update_node(course_id: UUID, node_id: UUID, body: UpdateNodeRequest, db: Session = Depends(get_db)):
    node = db.get(Node, node_id)
    if not node or node.course_id != course_id:
        raise HTTPException(status_code=404, detail="Node not found")

    if body.title is not None:
        node.title = body.title
    if body.depth is not None:
        node.depth = body.depth
    if body.order_index is not None:
        node.order_index = body.order_index

    db.flush()
    db.commit()
    return _node_to_dict(node, [])


@router.delete("/{course_id}/nodes/{node_id}", status_code=204)
def delete_node(course_id: UUID, node_id: UUID, db: Session = Depends(get_db)):
    node = db.get(Node, node_id)
    if not node or node.course_id != course_id:
        raise HTTPException(status_code=404, detail="Node not found")

    db.delete(node)
    db.flush()
    db.commit()


# --- Edge CRUD ---


@router.post("/{course_id}/edges", status_code=201)
def create_edge(course_id: UUID, body: CreateEdgeRequest, db: Session = Depends(get_db)):
    parent_uuid = UUID(body.parent_id)
    child_uuid = UUID(body.child_id)

    if parent_uuid == child_uuid:
        raise HTTPException(status_code=422, detail="Self-loops not allowed")

    # Verify both nodes belong to this course
    parent = db.get(Node, parent_uuid)
    child = db.get(Node, child_uuid)
    if not parent or parent.course_id != course_id:
        raise HTTPException(status_code=404, detail="Parent node not found")
    if not child or child.course_id != course_id:
        raise HTTPException(status_code=404, detail="Child node not found")

    # Check duplicate
    existing = db.get(NodeEdge, (parent_uuid, child_uuid))
    if existing:
        raise HTTPException(status_code=409, detail="Edge already exists")

    edge = NodeEdge(parent_id=parent_uuid, child_id=child_uuid, edge_type=body.edge_type)
    db.add(edge)
    db.flush()
    db.commit()
    return _edge_to_dict(edge)


@router.delete("/{course_id}/edges/{parent_id}/{child_id}", status_code=204)
def delete_edge(course_id: UUID, parent_id: UUID, child_id: UUID, db: Session = Depends(get_db)):
    edge = db.get(NodeEdge, (parent_id, child_id))
    if not edge:
        raise HTTPException(status_code=404, detail="Edge not found")

    db.delete(edge)
    db.flush()
    db.commit()
