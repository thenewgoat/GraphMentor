import tempfile
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, Depends
from sqlalchemy.orm import Session

from app.config import settings
from app.db.postgres import get_db
from app.services.ingest_pipeline import IngestPipeline

router = APIRouter(prefix="/ingest", tags=["ingestion"])


@router.post("/upload", status_code=201)
def upload_pdf(
    file: UploadFile = File(...),
    title: str = Form(...),
    course_id: str = Form(None),
    db: Session = Depends(get_db),
):
    # Validate file type
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=422, detail="Only PDF files are accepted")

    # Write to temp file
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        content = file.file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        cid = UUID(course_id) if course_id else None

        pipeline = IngestPipeline(
            db=db,
            upload_dir=Path("data/uploads"),
            openai_api_key=settings.openai_api_key,
        )
        result = pipeline.run(pdf_path=tmp_path, title=title, course_id=cid)
        db.commit()
        return result

    except ValueError as e:
        db.rollback()
        if "duplicate" in str(e).lower():
            raise HTTPException(status_code=409, detail=str(e))
        if "not found" in str(e).lower():
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {e}")
    finally:
        tmp_path.unlink(missing_ok=True)
