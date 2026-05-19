"""
Построение векторного индекса по чанкам через OpenAI embeddings
и поиск по нему.

Embeddings — превращение текста в вектор (список чисел), отражающий
смысл. Поиск по смыслу: находит близкие по содержанию чанки,
даже если слова разные. Дополняет BM25 (точные совпадения).
"""
from openai import OpenAI


# Модель эмбеддингов. Вынесена в константу — поменять = одна строка.
# Позже можно перейти на text-embedding-3-large.
EMBEDDING_MODEL = "text-embedding-3-small"


def get_embeddings(texts: list[str]) -> list[list[float]]:
    """
    Получает векторы (embeddings) для списка текстов одним запросом.

    OpenAI позволяет отправить много текстов за один запрос —
    это быстрее и дешевле, чем по одному.

    Возвращает список векторов. Порядок векторов совпадает
    с порядком входных текстов.
    """
    client = OpenAI()

    response = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=texts,
    )

    # response.data — список объектов, у каждого есть .embedding (вектор).
    # Порядок гарантированно совпадает с порядком входных текстов.
    return [item.embedding for item in response.data]


def build_searchable_text(chunk: dict) -> str:
    """
    Собирает текст чанка для индексации: «шапка» + содержание.

    Та же логика, что в BM25 — вектор должен отражать
    и содержание раздела, и его контекст (документ, заголовки).
    """
    return " ".join([
        chunk.get("document_title", ""),
        chunk.get("parent_section", ""),
        chunk.get("section_title", ""),
        chunk.get("text", ""),
    ])


def build_embeddings_index(chunks: list[dict]) -> dict:
    """
    Строит векторный индекс по списку чанков.

    Для каждого чанка получает embedding и связывает его с chunk_id.

    Возвращает словарь-индекс:
      {
        "model": имя модели эмбеддингов,
        "items": [
          {"chunk_id": "...", "embedding": [числа...]},
          ...
        ]
      }
    """
    # Собираем тексты для индексации (шапка + содержание)
    texts = [build_searchable_text(chunk) for chunk in chunks]

    # Получаем векторы одним батч-запросом
    embeddings = get_embeddings(texts)

    # Связываем каждый вектор с его chunk_id
    items = []
    for chunk, embedding in zip(chunks, embeddings):
        items.append({
            "chunk_id": chunk["chunk_id"],
            "embedding": embedding,
        })

    return {
        "model": EMBEDDING_MODEL,
        "items": items,
    }


import math


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """
    Косинусное сходство двух векторов.

    Возвращает число от -1 до 1: чем ближе к 1, тем более
    похожи тексты по смыслу.
    """
    # Скалярное произведение: сумма попарных произведений
    dot = sum(a * b for a, b in zip(vec_a, vec_b))

    # Длина (норма) каждого вектора: корень из суммы квадратов
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))

    # Защита от деления на ноль
    if norm_a == 0 or norm_b == 0:
        return 0.0

    return dot / (norm_a * norm_b)


def search_embeddings(
    index: dict,
    query: str,
    top_k: int = 5,
) -> list[tuple[str, float]]:
    """
    Ищет по векторному индексу.

    index — построенный индекс (результат build_embeddings_index);
    query — поисковый запрос;
    top_k — сколько лучших результатов вернуть.

    Возвращает список пар (chunk_id, score), отсортированный
    по убыванию смысловой близости.
    """
    # Получаем вектор запроса (get_embeddings принимает список,
    # поэтому передаём [query] и берём [0])
    query_embedding = get_embeddings([query])[0]

    # Считаем близость запроса к каждому чанку
    scored = []
    for item in index["items"]:
        score = cosine_similarity(query_embedding, item["embedding"])
        scored.append((item["chunk_id"], score))

    # Сортируем по убыванию близости, берём top_k
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored[:top_k]