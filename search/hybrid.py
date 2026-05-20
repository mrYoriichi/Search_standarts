"""
Этап 6: гибридный поиск.

Объединяет результаты BM25 и векторного поиска через
Reciprocal Rank Fusion (RRF) — слияние по позициям в выдаче,
а не по сырым score (они у двух методов в разных шкалах).
"""
from indexing.bm25_index import search_bm25
from indexing.embeddings_index import search_embeddings


# Сколько брать из каждого поиска перед слиянием.
# Берём с запасом, чтобы у RRF был материал для перестановок:
# хорошие чанки на 7-8-м месте у каждого метода имеют шанс всплыть в топ.
RETRIEVAL_DEPTH = 20

# Сглаживание в формуле RRF. 60 — традиционное значение из оригинальной статьи.
# Больше k → меньше разница между 1-м и 5-м местом.
RRF_K = 60


def reciprocal_rank_fusion(
    result_lists: list[list[tuple[str, float]]],
    k: int = RRF_K,
) -> list[tuple[str, float]]:
    """
    Слияние нескольких поисковых выдач через RRF.

    Для каждого чанка: score = sum(1 / (k + rank)) по всем спискам,
    где он встретился. rank — позиция в списке (0, 1, 2, ...).

    Возвращает объединённый список (chunk_id, rrf_score),
    отсортированный по убыванию score.
    """
    scores: dict[str, float] = {}

    for results in result_lists:
        for rank, (chunk_id, _) in enumerate(results):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)

    # Сортируем по убыванию итогового RRF-score
    return sorted(scores.items(), key=lambda pair: pair[1], reverse=True)


def hybrid_search(
    bm25: tuple,
    embeddings_index: dict,
    query: str,
    top_k: int = 5,
) -> list[tuple[str, float]]:
    """
    Гибридный поиск: BM25 + векторный, объединённые через RRF.

    bm25 — кортеж (BM25-индекс, список chunk_id в порядке индекса),
           результат build_bm25_index.
    embeddings_index — построенный векторный индекс.
    query — поисковый запрос.
    top_k — сколько лучших результатов вернуть.

    Возвращает список (chunk_id, rrf_score) длиной до top_k.
    """
    bm25_index, bm25_chunk_ids = bm25

    # Берём из каждого поиска с запасом, чтобы у RRF был материал
    bm25_results = search_bm25(bm25_index, bm25_chunk_ids, query, top_k=RETRIEVAL_DEPTH)
    embeddings_results = search_embeddings(embeddings_index, query, top_k=RETRIEVAL_DEPTH)

    fused = reciprocal_rank_fusion([bm25_results, embeddings_results])
    return fused[:top_k]


