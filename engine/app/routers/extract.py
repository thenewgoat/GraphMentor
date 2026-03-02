"""Endpoints for topic extraction, enrichment, and graph organization."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.db.postgres import get_db
from app.services.graph_builder import GraphBuilder
from app.services.enrich_service import EnrichService
from app.services.organize_service import OrganizeService
from app.services.validators import ValidationError

router = APIRouter(prefix="/extract", tags=["extraction"])


@router.post("/topics/{course_id}", status_code=201)
def extract_topics(
    course_id: UUID,
    document_id: UUID | None = None,
    max_depth: int = 3,
    db: Session = Depends(get_db),
):
    if document_id is None:
        raise HTTPException(status_code=422, detail="document_id query parameter required")

    builder = GraphBuilder(
        db=db,
        openai_api_key=settings.openai_api_key,
        model=settings.llm_model,
    )

    try:
        result = builder.run(course_id=course_id, document_id=document_id, max_depth=max_depth)
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
