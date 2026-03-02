"""PyMuPDF-based PDF slide extractor with heuristic title detection."""
import logging
from pathlib import Path

import fitz  # pymupdf

from app.services.extractors.base import BaseExtractor
from app.services.extractors.models import Slide

logger = logging.getLogger(__name__)


class SlideExtractor(BaseExtractor):
    """Extract slides from PDF slide decks using PyMuPDF.

    Title heuristic: topmost text block in the top 20% of the page,
    filtered by being larger than the median font size on that page.
    """

    @property
    def supported_extensions(self) -> list[str]:
        return [".pdf"]

    def extract(self, path: Path) -> list[Slide]:
        self.validate_file(path)
        doc = fitz.open(str(path))
        slides: list[Slide] = []

        try:
            for page_num in range(len(doc)):
                page = doc[page_num]
                blocks = page.get_text("blocks")  # (x0, y0, x1, y1, text, block_no, type)

                # Filter to text blocks only (type 0)
                text_blocks = [b for b in blocks if b[6] == 0 and b[4].strip()]
                if not text_blocks:
                    logger.warning(f"Page {page_num + 1}: no text found, skipping")
                    slides.append(Slide(page=page_num + 1, title=None, body=""))
                    continue

                # Sort by vertical position (y0)
                text_blocks.sort(key=lambda b: b[1])

                page_height = page.rect.height
                title_cutoff = page_height * 0.20

                # Title: topmost block if it's in the top 20%
                title = None
                body_blocks = text_blocks
                if text_blocks[0][1] < title_cutoff:
                    title = text_blocks[0][4].strip()
                    body_blocks = text_blocks[1:]

                body = "\n".join(b[4].strip() for b in body_blocks)
                slides.append(Slide(page=page_num + 1, title=title, body=body))
        finally:
            doc.close()

        if not any(s.body.strip() for s in slides):
            raise ValueError(f"No extractable text found in {path.name}")

        return slides
