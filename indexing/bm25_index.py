"""
Построение BM25-индекса по чанкам и поиск по нему.

BM25 — классический алгоритм поиска по словам (точные совпадения:
коды норм, числа, термины). Дополняет векторный поиск.
"""

import re

from rank_bm25 import BM25Okapi


def tokenize(text: str) -> list[str]:
    """
    Разбивает текст на слова (токены) для BM25.

    Приводит к нижнему регистру, оставляет только буквы и цифры.
    Без стемминга — для первой версии простой токенизации достаточно.
    """
    # \w+ — последовательности из букв/цифр/подчёркиваний.
    # re.UNICODE (по умолчанию) — \w понимает чешские буквы (č, ž, ...).
    tokens = re.findall(r"\w+", text.lower())
    return tokens


def tokenize_chunk(chunk: dict) -> list[str]:
    """
    Токенизирует один чанк для BM25: «шапка» (название документа, заголовки) +
    содержание. Так поиск находит и по содержанию, и по контексту раздела.

    Вынесено отдельно, чтобы токены можно было посчитать один раз и закешировать
    (см. backend/core/library_cache.py) — на каждый вопрос regex по всему корпусу
    не гоняем.
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
    """
    Строит BM25-индекс из уже токенизированных чанков.

    tokenized_corpus и chunk_ids идут в одном порядке. Сам BM25Okapi считает
    статистику корпуса (IDF) по переданному набору — поэтому при поиске по
    выбранным документам сюда передают токены только этих чанков.

    Возвращает (BM25-индекс, список chunk_id в порядке индекса).
    """
    return BM25Okapi(tokenized_corpus), chunk_ids


def build_bm25_index(chunks: list[dict]) -> tuple[BM25Okapi, list[str]]:
    """
    Строит BM25-индекс по списку чанков (токенизация на месте).

    Удобно для CLI/тестов, где кеша токенов нет. В backend используется путь
    через build_bm25_from_tokens с закешированными токенами.

    Возвращает (BM25-индекс, список chunk_id в порядке индекса).
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
    """
    Ищет по BM25-индексу.

    index     — построенный BM25-индекс;
    chunk_ids — список chunk_id (в порядке индекса);
    query     — поисковый запрос;
    top_k     — сколько лучших результатов вернуть.

    Возвращает список пар (chunk_id, score), отсортированный
    по убыванию релевантности.
    """
    tokenized_query = tokenize(query)

    # get_scores возвращает оценку релевантности для КАЖДОГО чанка
    scores = index.get_scores(tokenized_query)

    # Связываем chunk_id с их оценками
    scored = list(zip(chunk_ids, scores))

    # Сортируем по убыванию score, берём top_k
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored[:top_k]
