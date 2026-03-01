import hashlib
import logging
import shutil
from pathlib import Path

from sqlalchemy.orm import Session

from app.db.vector import get_chroma_client
from app.models.course import Course
from app.models.sentence import Sentence
from app.services.embedder import OpenAIEmbedder
from app.services.extractors.slide_extractor import SlideExtractor
from app.services.segmenter import SentenceSegmenter

logger = logging.getLogger(__name__)


class IngestPipeline:
    """Orchestrates PDF ingestion: extract -> segment -> embed -> store."""

    def __init__(self, db: Session, upload_dir: Path, openai_api_key: str):
        self.db = db
        self.upload_dir = upload_dir
        self.extractor = SlideExtractor()
        self.segmenter = SentenceSegmenter()
        self.embedder = OpenAIEmbedder(api_key=openai_api_key)

    def run(self, pdf_path: Path, title: str) -> dict:
        # 1. Hash check
        pdf_bytes = pdf_path.read_bytes()
        pdf_hash = hashlib.sha256(pdf_bytes).hexdigest()

        existing = self.db.query(Course).filter_by(source_pdf_hash=pdf_hash).first()
        if existing:
            raise ValueError(f"PDF duplicate: course '{existing.title}' has the same hash")

        # 2. Create course
        course = Course(
            title=title,
            source_pdf_path="",  # set after copy
            source_pdf_hash=pdf_hash,
            ingestion_status="processing",
        )
        self.db.add(course)
        self.db.flush()

        try:
            # 3. Copy PDF to upload dir
            self.upload_dir.mkdir(parents=True, exist_ok=True)
            dest = self.upload_dir / f"{course.id}.pdf"
            shutil.copy2(pdf_path, dest)
            course.source_pdf_path = str(dest)

            # 4. Extract slides
            slides = self.extractor.extract(pdf_path)
            pages_with_content = sum(1 for s in slides if s.body.strip())

            # 5. Segment into sentences
            raw_sentences = self.segmenter.segment(slides)

            # 6. Store sentences in Postgres
            sentence_models = []
            for rs in raw_sentences:
                s = Sentence(
                    course_id=course.id,
                    page=rs.page,
                    position=rs.position,
                    slide_title=rs.slide_title,
                    text=rs.text,
                    hash=hashlib.sha256(rs.text.encode()).hexdigest(),
                )
                sentence_models.append(s)
            self.db.add_all(sentence_models)
            self.db.flush()

            # 7. Embed and store in ChromaDB
            texts = [self.embedder.format_text(rs) for rs in raw_sentences]
            embeddings = self.embedder.get_embeddings(texts)

            client = get_chroma_client()
            collection = client.get_or_create_collection(
                name=f"course_{str(course.id).replace('-', '')}_sentences"
            )
            collection.add(
                ids=[str(s.id) for s in sentence_models],
                documents=[rs.text for rs in raw_sentences],
                embeddings=embeddings,
                metadatas=[
                    {
                        "sentence_id": str(s.id),
                        "page": rs.page,
                        "position": rs.position,
                        "slide_title": rs.slide_title or "",
                    }
                    for s, rs in zip(sentence_models, raw_sentences)
                ],
            )

            # 8. Mark complete
            course.ingestion_status = "complete"
            self.db.flush()

            return {
                "course_id": str(course.id),
                "title": course.title,
                "sentences_count": len(sentence_models),
                "pages_processed": pages_with_content,
                "status": "complete",
            }

        except Exception:
            logger.exception("Ingestion failed, rolling back")
            self.db.delete(course)
            self.db.flush()
            raise
