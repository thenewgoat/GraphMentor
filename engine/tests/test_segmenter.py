from app.services.segmenter import SentenceSegmenter
from app.services.extractors.models import Slide


class TestSentenceSegmenter:
    def setup_method(self):
        self.segmenter = SentenceSegmenter()

    def test_basic_segmentation(self):
        slides = [Slide(page=1, title="Intro", body="First sentence. Second sentence.")]
        sentences = self.segmenter.segment(slides)
        assert len(sentences) == 2
        assert sentences[0].text == "First sentence."
        assert sentences[1].text == "Second sentence."

    def test_preserves_page_and_title(self):
        slides = [Slide(page=3, title="My Topic", body="Hello world.")]
        sentences = self.segmenter.segment(slides)
        assert sentences[0].page == 3
        assert sentences[0].slide_title == "My Topic"

    def test_position_indexing(self):
        slides = [Slide(page=1, title=None, body="First one. Second one. Third one.")]
        sentences = self.segmenter.segment(slides)
        positions = [s.position for s in sentences]
        assert positions == [0, 1, 2]

    def test_handles_abbreviations(self):
        slides = [Slide(page=1, title=None, body="Dr. Smith went to Washington. He arrived at 3 p.m.")]
        sentences = self.segmenter.segment(slides)
        assert len(sentences) == 2
        assert "Dr. Smith" in sentences[0].text

    def test_handles_eg_abbreviation(self):
        slides = [Slide(page=1, title=None, body="Use structures e.g. arrays and lists. They are efficient.")]
        sentences = self.segmenter.segment(slides)
        assert len(sentences) == 2
        assert "e.g." in sentences[0].text

    def test_filters_empty_sentences(self):
        slides = [Slide(page=1, title=None, body="   \n\n  Real sentence.  \n ")]
        sentences = self.segmenter.segment(slides)
        assert len(sentences) == 1
        assert sentences[0].text == "Real sentence."

    def test_multiple_slides(self):
        slides = [
            Slide(page=1, title="A", body="Slide one."),
            Slide(page=2, title="B", body="Slide two."),
        ]
        sentences = self.segmenter.segment(slides)
        assert len(sentences) == 2
        assert sentences[0].page == 1
        assert sentences[1].page == 2

    def test_skips_empty_slides(self):
        slides = [
            Slide(page=1, title="A", body="Content here."),
            Slide(page=2, title=None, body=""),
            Slide(page=3, title="C", body="More content."),
        ]
        sentences = self.segmenter.segment(slides)
        assert len(sentences) == 2
        assert sentences[0].page == 1
        assert sentences[1].page == 3
