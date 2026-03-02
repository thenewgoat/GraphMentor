# engine/tests/test_chunker.py
import uuid

import pytest

from app.services.chunker import build_chunks_from_sentences


class MockSentence:
    """Mimics Sentence ORM model for testing without DB."""
    def __init__(self, id, page, position, slide_title, text):
        self.id = id
        self.page = page
        self.position = position
        self.slide_title = slide_title
        self.text = text


class TestBuildChunks:
    def test_groups_by_page(self):
        s1 = MockSentence(uuid.uuid4(), page=1, position=0, slide_title="Intro", text="First sentence.")
        s2 = MockSentence(uuid.uuid4(), page=1, position=1, slide_title="Intro", text="Second sentence.")
        s3 = MockSentence(uuid.uuid4(), page=2, position=0, slide_title="Body", text="Third sentence.")

        chunks, mapping = build_chunks_from_sentences([s1, s2, s3])

        assert len(chunks) == 2
        assert chunks[0]["index"] == 0
        assert chunks[0]["text"] == "First sentence. Second sentence."
        assert chunks[0]["page_number"] == 1
        assert chunks[0]["heading"] == "Intro"
        assert chunks[1]["index"] == 1
        assert chunks[1]["text"] == "Third sentence."
        assert chunks[1]["page_number"] == 2

    def test_chunk_sentence_mapping(self):
        id1, id2, id3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        s1 = MockSentence(id1, page=1, position=0, slide_title=None, text="A.")
        s2 = MockSentence(id2, page=1, position=1, slide_title=None, text="B.")
        s3 = MockSentence(id3, page=2, position=0, slide_title=None, text="C.")

        chunks, mapping = build_chunks_from_sentences([s1, s2, s3])

        assert mapping[0] == [id1, id2]
        assert mapping[1] == [id3]

    def test_sentences_sorted_by_position_within_page(self):
        s1 = MockSentence(uuid.uuid4(), page=1, position=2, slide_title=None, text="Third.")
        s2 = MockSentence(uuid.uuid4(), page=1, position=0, slide_title=None, text="First.")
        s3 = MockSentence(uuid.uuid4(), page=1, position=1, slide_title=None, text="Second.")

        chunks, mapping = build_chunks_from_sentences([s1, s2, s3])

        assert chunks[0]["text"] == "First. Second. Third."
