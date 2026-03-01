import pysbd

from app.services.extractors.models import Slide, RawSentence


class SentenceSegmenter:
    """Split slide body text into sentences using pySBD."""

    def __init__(self, language: str = "en"):
        self.segmenter = pysbd.Segmenter(language=language, clean=False)

    def segment(self, slides: list[Slide]) -> list[RawSentence]:
        sentences: list[RawSentence] = []

        for slide in slides:
            if not slide.body.strip():
                continue

            raw_sentences = self.segmenter.segment(slide.body)
            position = 0
            for text in raw_sentences:
                text = text.strip()
                if not text:
                    continue
                sentences.append(
                    RawSentence(
                        text=text,
                        page=slide.page,
                        position=position,
                        slide_title=slide.title,
                    )
                )
                position += 1

        return sentences
