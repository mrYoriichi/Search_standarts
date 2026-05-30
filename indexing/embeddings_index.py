"""
Построение векторного индекса по чанкам через OpenAI embeddings
и поиск по нему.

Embeddings — превращение текста в вектор (список чисел), отражающий
смысл. Поиск по смыслу: находит близкие по содержанию чанки,
даже если слова разные. Дополняет BM25 (точные совпадения).
"""
import math

import tiktoken
from openai import OpenAI


# Модель эмбеддингов. Вынесена в константу — поменять = одна строка.
EMBEDDING_MODEL = "text-embedding-3-large"

# Лимит OpenAI на один input — 8192 токена. Берём с запасом 8000, чтобы
# учесть возможные расхождения и быть уверенными. Чанки длиннее обрезаются
# до этого числа токенов перед отправкой. См. PROJECT_STATE.md, Known issues
# — «Большие чанки».
MAX_TOKENS_PER_EMBEDDING_TEXT = 8000

# Энкодер для text-embedding-3-large (тот же cl100k_base, что и у GPT-4).
# Создаём один раз на модуль — это дорого инициализировать.
_TOKENIZER = tiktoken.get_encoding("cl100k_base")


def get_embeddings(texts: list[str]) -> tuple[list[list[float]], int]:
    """
    Получает векторы (embeddings) для списка текстов одним запросом.

    OpenAI позволяет отправить много текстов за один запрос —
    это быстрее и дешевле, чем по одному.

    Возвращает кортеж (векторы, total_tokens). Порядок векторов
    совпадает с порядком входных текстов; total_tokens — сколько
    OpenAI насчитал по факту (для расчёта стоимости).
    """
    client = OpenAI()

    response = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=texts,
    )

    # response.data — список объектов, у каждого есть .embedding (вектор).
    # Порядок гарантированно совпадает с порядком входных текстов.
    vectors = [item.embedding for item in response.data]
    return vectors, response.usage.total_tokens


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


def build_embeddings_index(chunks: list[dict]) -> tuple[dict, int]:
    """
    Строит векторный индекс по списку чанков.

    Для каждого чанка получает embedding и связывает его с chunk_id.

    Возвращает кортеж (индекс, total_tokens). Формат индекса:
      {
        "model": имя модели эмбеддингов,
        "items": [
          {"chunk_id": "...", "embedding": [числа...]},
          ...
        ]
      }
    total_tokens — сколько токенов OpenAI насчитал на батч (для стоимости).
    """
    # Собираем тексты для индексации (шапка + содержание)
    texts = [build_searchable_text(chunk) for chunk in chunks]

    # Защитное обрезание для чанков, которые не влезают в лимит модели.
    # Считаем токены через tiktoken, обрезаем по токенам и декодируем обратно.
    # Полный текст остаётся в chunks.json и работает для BM25.
    for i, text in enumerate(texts):
        token_ids = _TOKENIZER.encode(text)
        if len(token_ids) > MAX_TOKENS_PER_EMBEDDING_TEXT:
            print(
                f"  [!] {chunks[i]['chunk_id']}: {len(token_ids)} токенов > "
                f"{MAX_TOKENS_PER_EMBEDDING_TEXT}, обрезаю для embedding"
            )
            truncated = token_ids[:MAX_TOKENS_PER_EMBEDDING_TEXT]
            texts[i] = _TOKENIZER.decode(truncated)

    # Получаем векторы одним батч-запросом
    embeddings, tokens = get_embeddings(texts)

    # Связываем каждый вектор с его chunk_id
    items = []
    for chunk, embedding in zip(chunks, embeddings):
        items.append({
            "chunk_id": chunk["chunk_id"],
            "embedding": embedding,
        })

    index = {
        "model": EMBEDDING_MODEL,
        "items": items,
    }
    return index, tokens


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
    # поэтому передаём [query] и берём [0]). Токены тут игнорируем —
    # для поиска цена несущественна.
    vectors, _ = get_embeddings([query])
    query_embedding = vectors[0]

    # Считаем близость запроса к каждому чанку
    scored = []
    for item in index["items"]:
        score = cosine_similarity(query_embedding, item["embedding"])
        scored.append((item["chunk_id"], score))

    # Сортируем по убыванию близости, берём top_k
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored[:top_k]