from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.db.postgres import get_db
from app.services.graph_builder import GraphBuilder
from app.services.validators import ValidationError

router = APIRouter(prefix="/extract", tags=["extraction"])


@router.post("/topics/{course_id}", status_code=201)
def extract_topics(
    course_id: UUID,
    max_depth: int = 3,
    db: Session = Depends(get_db),
):
    builder = GraphBuilder(
        db=db,
        openai_api_key=settings.openai_api_key,
        model=settings.llm_model,
    )

    try:
        result = builder.run(course_id=course_id, max_depth=max_depth)
        db.commit()
        return result

    except ValueError as e:
        db.rollback()
        msg = str(e)
        if "not found" in msg:
            raise HTTPException(status_code=404, detail=msg)
        if "expected" in msg and "status" in msg:
            raise HTTPException(status_code=409, detail=msg)
        raise HTTPException(status_code=422, detail=msg)
    except ValidationError as e:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Graph building failed: {e}")
