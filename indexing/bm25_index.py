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


def build_bm25_index(chunks: list[dict]) -> tuple[BM25Okapi, list[str]]:
    """
    Строит BM25-индекс по списку чанков.

    Для индекса используем текст чанка вместе с его «шапкой»
    (название документа, заголовки) — чтобы поиск находил
    и по содержанию, и по контексту раздела.

    Возвращает кортеж:
      - сам BM25-индекс;
      - список chunk_id в том же порядке, что и документы в индексе
        (нужен, чтобы по результату поиска понять, какой это чанк).
    """
    tokenized_corpus = []  # список токенизированных текстов
    chunk_ids = []         # chunk_id в том же порядке

    for chunk in chunks:
        # Собираем текст для индексации: шапка + содержание
        searchable_text = " ".join([
            chunk.get("document_title", ""),
            chunk.get("parent_section", ""),
            chunk.get("section_title", ""),
            chunk.get("text", ""),
        ])
        tokenized_corpus.append(tokenize(searchable_text))
        chunk_ids.append(chunk["chunk_id"])

    # BM25Okapi принимает список токенизированных документов
    index = BM25Okapi(tokenized_corpus)
    return index, chunk_ids


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