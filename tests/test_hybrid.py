"""Tests of merging search results (search/hybrid.py).

The searches themselves (BM25, vector) are mocked here: vector search calls
OpenAI for the query embedding, and only the merge logic matters.
"""

from search.hybrid import reciprocal_rank_fusion, search_by_mode


def test_rrf_chunk_in_both_lists_wins():
    # 'b' appears in both result lists -> its total RRF score is higher
    # than the single-list leaders'.
    bm25 = [("a", 5.0), ("b", 3.0)]
    vector = [("b", 0.9), ("c", 0.8)]
    fused = reciprocal_rank_fusion([bm25, vector])
    assert fused[0][0] == "b"
    assert [chunk_id for chunk_id, _ in fused] == ["b", "a", "c"]


def test_rrf_empty_input():
    assert reciprocal_rank_fusion([]) == []
    assert reciprocal_rank_fusion([[], []]) == []


def test_mode_hybrid_dedup_vector_first(monkeypatch):
    # hybrid: vector goes first, BM25 duplicates are not repeated,
    # the order within each list is preserved (no re-sorting).
    monkeypatch.setattr(
        "search.hybrid.search_embeddings",
        lambda index, query, top_k: [("v1", 0.9), ("common", 0.8), ("v2", 0.7)],
    )
    monkeypatch.setattr(
        "search.hybrid.search_bm25",
        lambda index, ids, query, top_k: [("common", 7.0), ("k1", 5.0)],
    )
    result = search_by_mode((None, []), {}, "dotaz", mode="hybrid")
    assert result == ["v1", "common", "v2", "k1"]


def test_mode_vector_returns_only_vector(monkeypatch):
    monkeypatch.setattr(
        "search.hybrid.search_embeddings",
        lambda index, query, top_k: [("v1", 0.9), ("v2", 0.8)],
    )
    monkeypatch.setattr(
        "search.hybrid.search_bm25",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("BM25 must not be called in vector mode")
        ),
    )
    assert search_by_mode((None, []), {}, "dotaz", mode="vector") == ["v1", "v2"]


def test_mode_keyword_returns_only_bm25(monkeypatch):
    monkeypatch.setattr(
        "search.hybrid.search_bm25",
        lambda index, ids, query, top_k: [("k1", 7.0), ("k2", 5.0)],
    )
    monkeypatch.setattr(
        "search.hybrid.search_embeddings",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("vector must not be called in keyword mode")
        ),
    )
    assert search_by_mode((None, []), {}, "dotaz", mode="keyword") == ["k1", "k2"]
