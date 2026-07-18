"""
Построение векторного индекса по чанкам через OpenAI embeddings
и поиск по нему.

Embeddings — превращение текста в вектор (список чисел), отражающий
смысл. Поиск по смыслу: находит близкие по содержанию чанки,
даже если слова разные. Дополняет BM25 (точные совпадения).
"""

import numpy as np
import tiktoken
from openai import OpenAI


# Модель эмбеддингов. Вынесена в константу — поменять = одна строка.
EMBEDDING_MODEL = "text-embedding-3-large"

# Лимит OpenAI на один input — 8192 токена. Берём с запасом 8000, чтобы
# учесть возможные расхождения и быть уверенными. Чанки длиннее обрезаются
# до этого числа токенов перед отправкой. См. PROJECT_STATE.md, Known issues
# — «Большие чанки».
MAX_TOKENS_PER_EMBEDDING_TEXT = 8000

# Лимиты OpenAI на ОДИН запрос embeddings: ~300k токенов суммарно и 2048
# текстов. Берём с запасом (tiktoken может насчитать чуть меньше сервера).
# Большой документ одним запросом падал бы на последнем шаге пайплайна,
# когда vision уже оплачен — поэтому шлём партиями.
MAX_TOKENS_PER_REQUEST = 250_000
MAX_TEXTS_PER_REQUEST = 1000

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
    return " ".join(
        [
            chunk.get("document_title", ""),
            chunk.get("parent_section", ""),
            chunk.get("section_title", ""),
            chunk.get("text", ""),
        ]
    )


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
    total_tokens — сколько токенов OpenAI насчитал суммарно (для стоимости).
    """
    if not chunks:
        raise ValueError(
            "Нет чанков для индексации — в документе не нашлось извлекаемого текста."
        )

    # Собираем тексты для индексации (шапка + содержание)
    texts = [build_searchable_text(chunk) for chunk in chunks]

    # Защитное обрезание для чанков, которые не влезают в лимит модели.
    # Считаем токены через tiktoken, обрезаем по токенам и декодируем обратно.
    # Полный текст остаётся в chunks.json и работает для BM25.
    token_counts: list[int] = []
    for i, text in enumerate(texts):
        token_ids = _TOKENIZER.encode(text)
        if len(token_ids) > MAX_TOKENS_PER_EMBEDDING_TEXT:
            print(
                f"  [!] {chunks[i]['chunk_id']}: {len(token_ids)} токенов > "
                f"{MAX_TOKENS_PER_EMBEDDING_TEXT}, обрезаю для embedding"
            )
            token_ids = token_ids[:MAX_TOKENS_PER_EMBEDDING_TEXT]
            texts[i] = _TOKENIZER.decode(token_ids)
        token_counts.append(len(token_ids))

    # Режем тексты на партии под лимиты одного запроса (порядок сохраняется).
    batches: list[list[str]] = [[]]
    batch_tokens = 0
    for text, n_tokens in zip(texts, token_counts):
        batch_full = batch_tokens + n_tokens > MAX_TOKENS_PER_REQUEST or (
            len(batches[-1]) >= MAX_TEXTS_PER_REQUEST
        )
        if batches[-1] and batch_full:
            batches.append([])
            batch_tokens = 0
        batches[-1].append(text)
        batch_tokens += n_tokens

    embeddings: list[list[float]] = []
    tokens = 0
    for n, batch in enumerate(batches, start=1):
        if len(batches) > 1:
            print(f"  эмбеддинги: партия {n}/{len(batches)} ({len(batch)} текстов)")
        vectors, used = get_embeddings(batch)
        embeddings.extend(vectors)
        tokens += used

    # Связываем каждый вектор с его chunk_id
    items = []
    for chunk, embedding in zip(chunks, embeddings):
        items.append(
            {
                "chunk_id": chunk["chunk_id"],
                "embedding": embedding,
            }
        )

    index = {
        "model": EMBEDDING_MODEL,
        "items": items,
    }
    return index, tokens


def build_matrix_index(items: list[dict], model: str) -> dict:
    """
    Превращает список items (с диска) в матричный индекс для быстрого поиска.

    На диске эмбеддинги лежат как списки float ({chunk_id, embedding}). Держать
    их так в памяти дорого (на 30к чанков — гигабайты) и медленно искать (цикл
    на Python). Поэтому при загрузке складываем все векторы в одну float32-матрицу
    (N, D) и нормируем каждую строку (делим на длину). Тогда косинусное сходство
    с нормированным запросом — это просто скалярное произведение, а значит весь
    поиск — одно матричное умножение.

    Формат индекса в памяти:
      {
        "model": имя модели эмбеддингов,
        "chunk_ids": [...],          # порядок совпадает со строками матрицы
        "matrix": np.ndarray (N, D), # float32, строки нормированы (L2)
      }
    """
    chunk_ids = [item["chunk_id"] for item in items]
    matrix = np.asarray([item["embedding"] for item in items], dtype=np.float32)

    # Нормируем строки: делим каждый вектор на его длину. keepdims — чтобы
    # форма (N, 1) транслировалась на (N, D). Нулевые векторы защищаем от
    # деления на ноль (норму подменяем на 1 — вектор остаётся нулевым).
    if matrix.size:
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        matrix /= norms

    return {"model": model, "chunk_ids": chunk_ids, "matrix": matrix}


def search_embeddings(
    index: dict,
    query: str,
    top_k: int = 5,
) -> list[tuple[str, float]]:
    """
    Ищет по матричному индексу (результат build_matrix_index).

    index — индекс с нормированной матрицей и параллельным списком chunk_ids;
    query — поисковый запрос;
    top_k — сколько лучших результатов вернуть.

    Возвращает список пар (chunk_id, score), отсортированный
    по убыванию смысловой близости.
    """
    matrix = index["matrix"]
    chunk_ids = index["chunk_ids"]
    if matrix.shape[0] == 0:
        return []

    # Вектор запроса (get_embeddings принимает список — даём [query], берём [0]).
    # Токены тут игнорируем: для поиска цена несущественна.
    vectors, _ = get_embeddings([query])
    query_vec = np.asarray(vectors[0], dtype=np.float32)
    norm = np.linalg.norm(query_vec)
    if norm != 0:
        query_vec /= norm

    # Строки матрицы и запрос нормированы → скалярное произведение = косинус.
    # Одно умножение (N, D) @ (D,) даёт сразу все N оценок.
    scores = matrix @ query_vec

    # Берём top_k без полной сортировки всех N: argpartition выносит k лучших
    # вперёд за O(N), затем сортируем только эти k.
    k = min(top_k, scores.shape[0])
    top_idx = np.argpartition(-scores, k - 1)[:k]
    top_idx = top_idx[np.argsort(-scores[top_idx])]
    return [(chunk_ids[i], float(scores[i])) for i in top_idx]
