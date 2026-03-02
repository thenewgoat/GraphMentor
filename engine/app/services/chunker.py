# engine/app/services/chunker.py
from itertools import groupby
from uuid import UUID


def build_chunks_from_sentences(sentences) -> tuple[list[dict], dict[int, list[UUID]]]:
    """Group sentences by page into chunks for LLM input.

    Returns:
        chunks: List of {"index", "text", "page_number", "heading"} dicts.
        chunk_sentence_map: Dict mapping chunk index -> list of sentence UUIDs.
    """
    chunks = []
    chunk_sentence_map = {}

    # Sort by page, then position
    sorted_sentences = sorted(sentences, key=lambda s: (s.page, s.position))

    for page_num, group in groupby(sorted_sentences, key=lambda s: s.page):
        page_sentences = list(group)
        idx = len(chunks)
        chunks.append({
            "index": idx,
            "text": " ".join(s.text for s in page_sentences),
            "page_number": page_num,
            "heading": page_sentences[0].slide_title,
        })
        chunk_sentence_map[idx] = [s.id for s in page_sentences]

    return chunks, chunk_sentence_map
