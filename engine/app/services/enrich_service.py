"""Stage 3: Enrich thin nodes via Wikipedia search and LLM summarization."""
import logging
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.course import Course
from app.models.node import Node
from app.models.document import NodePage, Page, Reference
from app.services.llm_client import LLMClient
from app.config import settings

logger = logging.getLogger(__name__)


class EnrichService:
    """Stage 3: Enrich thin nodes with Wikipedia search results."""

    def __init__(self, db: Session, openai_api_key: str, model: str = "gpt-4o-mini"):
        self.db = db
        self.llm = LLMClient(api_key=openai_api_key, model=model)

    def run(self, course_id: UUID) -> dict:
        course = self.db.query(Course).filter_by(id=course_id).first()
        if not course:
            raise ValueError(f"Course {course_id} not found")

        # Load references for search context
        refs = self.db.query(Reference).filter_by(course_id=course_id).all()
        book_titles = [r.title for r in refs if r.ref_type == "book"]

        nodes = self.db.query(Node).filter_by(course_id=course_id).all()
        threshold = settings.enrichment_word_threshold

        enriched = 0
        skipped = 0

        for node in nodes:
            # Get page text for this node
            page_rows = (
                self.db.query(Page)
                .join(NodePage, NodePage.page_id == Page.id)
                .filter(NodePage.node_id == node.id)
                .all()
            )
            page_text = "\n\n".join(p.body for p in page_rows)
            word_count = len(page_text.split())

            if word_count >= threshold and not node.supplementary_content:
                skipped += 1
                continue

            # Wikipedia search
            search_results = self._wiki_search(node.title, book_titles)
            if not search_results:
                skipped += 1
                continue

            # LLM summarization
            summary = self.llm.enrich_topic(
                title=node.title,
                keywords=[],
                page_text=page_text,
                search_results=search_results,
            )
            node.supplementary_content = summary
            enriched += 1

        self.db.flush()
        return {"nodes_enriched": enriched, "nodes_skipped": skipped}

    def _wiki_search(self, title: str, book_titles: list[str]) -> str:
        """Search Wikipedia for supplementary content."""
        try:
            import wikipedia

            queries = [title]
            if book_titles:
                queries.append(f"{title} {book_titles[0]}")

            results = []
            for query in queries[:2]:
                try:
                    page = wikipedia.page(query, auto_suggest=True)
                    summary = page.summary
                    if len(summary) > 1000:
                        summary = summary[:1000] + "..."
                    results.append(f"**{page.title}**\n{summary}")
                except (wikipedia.DisambiguationError, wikipedia.PageError):
                    # Try search instead
                    search_results = wikipedia.search(query, results=3)
                    for sr_title in search_results[:2]:
                        try:
                            page = wikipedia.page(sr_title, auto_suggest=False)
                            summary = page.summary
                            if len(summary) > 500:
                                summary = summary[:500] + "..."
                            results.append(f"**{page.title}**\n{summary}")
                        except Exception:
                            continue

            return "\n\n---\n\n".join(results[:3])
        except Exception:
            logger.warning(f"Wikipedia search failed for '{title}'", exc_info=True)
            return ""
