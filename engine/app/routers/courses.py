from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.postgres import get_db
from app.models.course import Course
from app.models.node import Node, NodeEdge
from app.models.sentence import NodeSentence, Sentence


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

router = APIRouter(prefix="/courses", tags=["courses"])


def _course_to_dict(course: Course) -> dict:
    return {
        "id": str(course.id),
        "title": course.title,
        "description": course.description,
        "source_pdf_path": course.source_pdf_path,
        "source_pdf_hash": course.source_pdf_hash,
        "mastery_threshold": course.mastery_threshold,
        "time_decay_lambda": course.time_decay_lambda,
        "max_follow_ups_per_session": course.max_follow_ups_per_session,
        "topic_radius": course.topic_radius,
        "ingestion_status": course.ingestion_status,
        "created_at": course.created_at.isoformat() if course.created_at else None,
        "updated_at": course.updated_at.isoformat() if course.updated_at else None,
    }


@router.get("")
def list_courses(db: Session = Depends(get_db)):
    courses = db.query(Course).order_by(Course.created_at.desc()).all()
    return [_course_to_dict(c) for c in courses]


def _node_to_dict(node: Node, sentences: list[dict]) -> dict:
    return {
        "id": str(node.id),
        "course_id": str(node.course_id),
        "title": node.title,
        "parent_ids": [str(p) for p in (node.parent_ids or [])],
        "child_ids": [str(c) for c in (node.child_ids or [])],
        "depth": node.depth,
        "order_index": node.order_index,
        "application_examples": node.application_examples,
        "sentences": sentences,
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

    # Batch-load sentences per node
    node_ids = [n.id for n in nodes]
    node_sentence_rows = (
        db.query(NodeSentence.node_id, Sentence)
        .join(Sentence, NodeSentence.sentence_id == Sentence.id)
        .filter(NodeSentence.node_id.in_(node_ids))
        .order_by(Sentence.page, Sentence.position)
        .all()
    ) if node_ids else []

    sentences_by_node: dict[str, list[dict]] = {}
    for node_id, sentence in node_sentence_rows:
        key = str(node_id)
        sentences_by_node.setdefault(key, []).append({
            "id": str(sentence.id),
            "page": sentence.page,
            "position": sentence.position,
            "slide_title": sentence.slide_title,
            "text": sentence.text,
        })

    return {
        "nodes": [_node_to_dict(n, sentences_by_node.get(str(n.id), [])) for n in nodes],
        "edges": [_edge_to_dict(e) for e in edges],
    }


@router.get("/{course_id}")
def get_course(course_id: UUID, db: Session = Depends(get_db)):
    course = db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    return _course_to_dict(course)


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
