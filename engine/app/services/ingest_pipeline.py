"""Stage 0: Upload PDF, extract pages, embed in ChromaDB, store in Postgres."""
import hashlib
import logging
import shutil
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.vector import get_chroma_client
from app.models.course import Course
from app.models.document import Document, Page
from app.services.embedder import OpenAIEmbedder
from app.services.extractors.slide_extractor import SlideExtractor

logger = logging.getLogger(__name__)


class IngestPipeline:
    """Stage 0: Upload PDF, extract pages, embed, store."""

    def __init__(self, db: Session, upload_dir: Path, openai_api_key: str):
        self.db = db
        self.upload_dir = upload_dir
        self.extractor = SlideExtractor()
        self.embedder = OpenAIEmbedder(api_key=openai_api_key)

    def run(self, pdf_path: Path, title: str, course_id=None) -> dict:
        pdf_bytes = pdf_path.read_bytes()
        pdf_hash = hashlib.sha256(pdf_bytes).hexdigest()

        # Create or fetch course
        if course_id:
            course = self.db.query(Course).filter_by(id=course_id).first()
            if not course:
                raise ValueError(f"Course {course_id} not found")
            # Check duplicate within course
            existing = (
                self.db.query(Document)
                .filter_by(course_id=course_id, file_hash=pdf_hash)
                .first()
            )
            if existing:
                raise ValueError(
                    f"PDF duplicate: document '{existing.title}' in this course has the same hash"
                )
        else:
            course = Course(title=title, ingestion_status="pending")
            self.db.add(course)
            self.db.flush()

        # Compute upload_order
        max_order = (
            self.db.query(func.max(Document.upload_order))
            .filter_by(course_id=course.id)
            .scalar()
        )
        upload_order = (max_order or 0) + 1

        # Create document
        document = Document(
            course_id=course.id,
            title=title,
            filename=pdf_path.name,
            file_path="",
            file_hash=pdf_hash,
            upload_order=upload_order,
            ingestion_status="processing",
        )
        self.db.add(document)
        self.db.flush()

        try:
            # Copy PDF
            self.upload_dir.mkdir(parents=True, exist_ok=True)
            dest = self.upload_dir / f"{document.id}.pdf"
            shutil.copy2(pdf_path, dest)
            document.file_path = str(dest)

            # Extract slides
            slides = self.extractor.extract(pdf_path)

            # Compute global_page offset
            max_global = (
                self.db.query(func.max(Page.global_page))
                .filter_by(course_id=course.id)
                .scalar()
            )
            global_offset = max_global or 0

            # Store pages
            page_models = []
            for slide in slides:
                if not slide.body.strip():
                    continue
                page = Page(
                    document_id=document.id,
                    course_id=course.id,
                    page_number=slide.page,
                    global_page=global_offset + slide.page,
                    slide_title=slide.title,
                    body=slide.body,
                )
                page_models.append(page)
            self.db.add_all(page_models)
            document.page_count = len(page_models)
            self.db.flush()

            # Embed pages in ChromaDB
            texts = []
            for p in page_models:
                prefix = f"[{p.slide_title}] " if p.slide_title else ""
                texts.append(f"{prefix}{p.body}")

            if texts:
                embeddings = self.embedder.get_embeddings(texts)
                client = get_chroma_client()
                collection = client.get_or_create_collection(
                    name=f"course_{str(course.id).replace('-', '')}_pages"
                )
                collection.add(
                    ids=[str(p.id) for p in page_models],
                    documents=[p.body for p in page_models],
                    embeddings=embeddings,
                    metadatas=[
                        {
                            "page_id": str(p.id),
                            "document_id": str(document.id),
                            "page_number": p.page_number,
                            "global_page": p.global_page,
                            "slide_title": p.slide_title or "",
                        }
                        for p in page_models
                    ],
                )

            # Mark complete
            document.ingestion_status = "complete"
            if course.ingestion_status == "pending":
                course.ingestion_status = "complete"
            self.db.flush()

            return {
                "course_id": str(course.id),
                "document_id": str(document.id),
                "title": document.title,
                "pages_count": len(page_models),
                "upload_order": upload_order,
                "status": "complete",
            }

        except Exception:
            logger.exception("Ingestion failed")
            self.db.delete(document)
            self.db.flush()
            raise
