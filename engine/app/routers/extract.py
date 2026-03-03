"""Endpoints for topic extraction, enrichment, and graph organization."""
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.db.postgres import get_db
from app.models.node import Node, NodeEdge
from app.models.document import Document, NodePage
from app.services.graph_builder import GraphBuilder
from app.services.enrich_service import EnrichService
from app.services.organize_service import OrganizeService
from app.services.validators import ValidationError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/extract", tags=["extraction"])


@router.post("/topics/{course_id}", status_code=201)
def extract_topics(
    course_id: UUID,
    document_id: UUID | None = None,
    max_depth: int = 4,
    db: Session = Depends(get_db),
):
    """Extract topics from a single document or all unextracted documents in a course."""
    builder = GraphBuilder(
        db=db,
        openai_api_key=settings.openai_api_key,
        model=settings.llm_model,
    )

    if document_id is not None:
        # Single-document extraction (existing behavior)
        return _extract_single(builder, db, course_id, document_id, max_depth)

    # Generate graph: destroy existing graph, rebuild from all documents
    all_docs = (
        db.query(Document)
        .filter_by(course_id=course_id, ingestion_status="complete")
        .order_by(Document.upload_order)
        .all()
    )

    if not all_docs:
        raise HTTPException(status_code=422, detail="No documents found for this course")

    # Clear existing graph (keep Miscellaneous group)
    from app.db.vector import delete_collection
    delete_collection(str(course_id))
    existing_nodes = db.query(Node).filter_by(course_id=course_id).all()
    for node in existing_nodes:
        if node.title == "Miscellaneous" and node.node_type == "group":
            continue
        db.delete(node)
    db.flush()
    logger.info("[Extract] Cleared existing graph for course %s", course_id)

    try:
        result = builder.build_full_graph(course_id=course_id, documents=all_docs, max_depth=max_depth)
        db.commit()
        return result
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(e))
    except ValidationError as e:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        db.rollback()
        logger.error("Full graph build failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Graph building failed: {e}")


def _extract_single(builder, db, course_id, document_id, max_depth):
    """Extract topics from a single document, then auto-organize."""
    try:
        result = builder.run(course_id=course_id, document_id=document_id, max_depth=max_depth)
        db.flush()

        # Auto-organize: suggest and apply all
        organize_result = _auto_organize(db, course_id)
        result["organized"] = organize_result

        db.commit()
        return result
    except ValueError as e:
        db.rollback()
        msg = str(e)
        if "not found" in msg:
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=422, detail=msg)
    except ValidationError as e:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Graph building failed: {e}")


def _auto_organize(db: Session, course_id: UUID) -> dict:
    """Run organize suggestions and auto-apply all of them.

    Uses a savepoint so failures here don't lose the already-built graph.
    """
    try:
        nested = db.begin_nested()
        service = OrganizeService(
            db=db, openai_api_key=settings.openai_api_key, model=settings.llm_model
        )
        suggestions = service.suggest(course_id=course_id)
        if not suggestions:
            logger.info("[Organize] No suggestions — graph already clean")
            return {"suggestions": 0, "applied": 0}

        all_ids = [s["id"] for s in suggestions]
        apply_result = service.apply(
            course_id=course_id, suggestion_ids=all_ids, suggestions=suggestions
        )
        logger.info(
            "[Organize] Auto-applied %d/%d suggestions",
            apply_result["applied"], len(suggestions),
        )
        return {"suggestions": len(suggestions), "applied": apply_result["applied"]}
    except Exception:
        db.rollback()  # rollback to savepoint, preserving the outer transaction
        logger.warning("Auto-organize failed, continuing without", exc_info=True)
        return {"suggestions": 0, "applied": 0, "error": "auto-organize failed"}


@router.post("/enrich/{course_id}")
def enrich_course(course_id: UUID, db: Session = Depends(get_db)):
    service = EnrichService(
        db=db, openai_api_key=settings.openai_api_key, model=settings.llm_model
    )
    try:
        result = service.run(course_id=course_id)
        db.commit()
        return result
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Enrichment failed: {e}")


# In-memory suggestion cache (simple dict, keyed by course_id)
_suggestion_cache: dict[str, list[dict]] = {}


@router.post("/organize/{course_id}")
def organize_course(course_id: UUID, db: Session = Depends(get_db)):
    service = OrganizeService(
        db=db, openai_api_key=settings.openai_api_key, model=settings.llm_model
    )
    try:
        suggestions = service.suggest(course_id=course_id)
        _suggestion_cache[str(course_id)] = suggestions
        db.commit()
        return {"suggestions": suggestions}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Organization failed: {e}")


class ApplyOrganizeRequest(BaseModel):
    suggestion_ids: list[int]


@router.post("/organize/{course_id}/apply")
def apply_organization(course_id: UUID, body: ApplyOrganizeRequest, db: Session = Depends(get_db)):
    suggestions = _suggestion_cache.get(str(course_id), [])
    if not suggestions:
        raise HTTPException(status_code=404, detail="No pending suggestions. Run organize first.")

    service = OrganizeService(
        db=db, openai_api_key=settings.openai_api_key, model=settings.llm_model
    )
    try:
        result = service.apply(course_id=course_id, suggestion_ids=body.suggestion_ids, suggestions=suggestions)
        _suggestion_cache.pop(str(course_id), None)
        db.commit()
        return result
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Apply failed: {e}")
