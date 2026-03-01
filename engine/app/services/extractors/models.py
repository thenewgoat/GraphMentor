from dataclasses import dataclass


@dataclass
class Slide:
    """Extracted slide with title and body text."""
    page: int           # 1-indexed
    title: str | None   # detected from top text block
    body: str           # remaining text on the slide


@dataclass
class RawSentence:
    """A single sentence with source metadata."""
    text: str
    page: int           # 1-indexed, from parent Slide
    position: int       # 0-indexed within page
    slide_title: str | None
