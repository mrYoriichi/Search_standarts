"""Hybrid search.

Merges BM25 and vector results via Reciprocal Rank Fusion (RRF) —
fusion by rank positions, not raw scores (the two methods score on
different scales).
"""

from indexing.bm25_index import search_bm25
from indexing.embeddings_index import search_embeddings


# How much to take from each search before fusion. Extra depth gives RRF
# material to reorder: good chunks ranked 7th-8th by one method can still
# surface in the top.
RETRIEVAL_DEPTH = 20

# RRF smoothing; 60 is the traditional value from the original paper.
# Larger k → smaller difference between 1st and 5th place.
RRF_K = 60


def reciprocal_rank_fusion(
    result_lists: list[list[tuple[str, float]]],
    k: int = RRF_K,
) -> list[tuple[str, float]]:
    """Fuse several result lists via RRF.

    Per chunk: score = sum(1 / (k + rank)) over every list it appears in;
    rank is the position (0, 1, 2, ...). Returns (chunk_id, rrf_score)
    sorted by descending score.
    """
    scores: dict[str, float] = {}

    for results in result_lists:
        for rank, (chunk_id, _) in enumerate(results):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)

    return sorted(scores.items(), key=lambda pair: pair[1], reverse=True)


def hybrid_search(
    bm25: tuple,
    embeddings_index: dict,
    query: str,
    top_k: int = 5,
) -> list[tuple[str, float]]:
    """BM25 + vector search fused via RRF.

    bm25 is the (index, chunk_ids) tuple from build_bm25_index.
    Returns up to top_k (chunk_id, rrf_score) pairs.
    """
    bm25_index, bm25_chunk_ids = bm25

    bm25_results = search_bm25(bm25_index, bm25_chunk_ids, query, top_k=RETRIEVAL_DEPTH)
    embeddings_results = search_embeddings(
        embeddings_index, query, top_k=RETRIEVAL_DEPTH
    )

    fused = reciprocal_rank_fusion([bm25_results, embeddings_results])
    return fused[:top_k]


# App search modes and how many chunks each sends to the model.
SEARCH_MODES = ("hybrid", "vector", "keyword")
VECTOR_ONLY_K = 20  # "vector":  top-20 of vector search
KEYWORD_ONLY_K = 10  # "keyword": top-10 of BM25
HYBRID_EACH = 7  # "hybrid":  7 from vector + 7 from BM25, merged


def search_by_mode(
    bm25: tuple,
    embeddings_index: dict,
    query: str,
    mode: str = "hybrid",
) -> list[str]:
    """Chunk ids for the model, depending on the search mode.

    - "vector":  top of the vector search (by meaning).
    - "keyword": top of BM25 (by words).
    - "hybrid":  top-7 of each, merged with duplicates removed (vector
                 first); 7-14 unique chunks.

    Unlike hybrid_search (RRF) the chunks are not re-ranked here — the
    modes exist to compare search behaviour in the UI.
    """
    bm25_index, bm25_chunk_ids = bm25

    if mode == "vector":
        results = search_embeddings(embeddings_index, query, top_k=VECTOR_ONLY_K)
        return [chunk_id for chunk_id, _ in results]

    if mode == "keyword":
        results = search_bm25(bm25_index, bm25_chunk_ids, query, top_k=KEYWORD_ONLY_K)
        return [chunk_id for chunk_id, _ in results]

    # hybrid: merge the two lists, drop duplicates, keep order.
    vec = search_embeddings(embeddings_index, query, top_k=HYBRID_EACH)
    kw = search_bm25(bm25_index, bm25_chunk_ids, query, top_k=HYBRID_EACH)
    ordered: list[str] = []
    for chunk_id, _ in [*vec, *kw]:
        if chunk_id not in ordered:
            ordered.append(chunk_id)
    return ordered
