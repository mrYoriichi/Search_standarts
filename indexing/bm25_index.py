"""BM25 index construction and search.

BM25 is classic keyword search (exact matches: standard codes, numbers,
terms). It complements the vector search.
"""

import re

from rank_bm25 import BM25Okapi


def tokenize(text: str) -> list[str]:
    """Split text into lowercase word tokens; no stemming."""
    # \w+ with re.UNICODE (the default) understands Czech letters (č, ž, ...).
    return re.findall(r"\w+", text.lower())


def tokenize_chunk(chunk: dict) -> list[str]:
    """Tokenize one chunk: header (document title, headings) + body.

    Separate function so tokens can be computed once and cached
    (backend/core/library_cache.py) instead of re-tokenizing the whole
    corpus on every question.
    """
    searchable_text = " ".join(
        [
            chunk.get("document_title", ""),
            chunk.get("parent_section", ""),
            chunk.get("section_title", ""),
            chunk.get("text", ""),
        ]
    )
    return tokenize(searchable_text)


def build_bm25_from_tokens(
    tokenized_corpus: list[list[str]],
    chunk_ids: list[str],
) -> tuple[BM25Okapi, list[str]]:
    """Build a BM25 index from pre-tokenized chunks.

    tokenized_corpus and chunk_ids share one order. BM25Okapi computes
    corpus statistics (IDF) over exactly what it gets — a filtered search
    passes only the tokens of the selected chunks.
    """
    return BM25Okapi(tokenized_corpus), chunk_ids


def build_bm25_index(chunks: list[dict]) -> tuple[BM25Okapi, list[str]]:
    """Build a BM25 index, tokenizing on the spot.

    For CLI/tests where no token cache exists; the backend goes through
    build_bm25_from_tokens with cached tokens.
    """
    tokenized_corpus = [tokenize_chunk(chunk) for chunk in chunks]
    chunk_ids = [chunk["chunk_id"] for chunk in chunks]
    return build_bm25_from_tokens(tokenized_corpus, chunk_ids)


def search_bm25(
    index: BM25Okapi,
    chunk_ids: list[str],
    query: str,
    top_k: int = 5,
) -> list[tuple[str, float]]:
    """Search the index; returns (chunk_id, score) sorted by relevance."""
    tokenized_query = tokenize(query)
    scores = index.get_scores(tokenized_query)  # a score for EVERY chunk
    scored = list(zip(chunk_ids, scores))
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored[:top_k]
