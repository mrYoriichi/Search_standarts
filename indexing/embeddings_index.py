"""Vector index over chunks via OpenAI embeddings, and search over it.

Semantic search: finds chunks close in meaning even when the words
differ. Complements BM25 (exact matches).
"""

import numpy as np
import tiktoken
from openai import BadRequestError, OpenAI


# Changing the embedding model is a one-line change here.
EMBEDDING_MODEL = "text-embedding-3-large"

# OpenAI's per-input limit is 8192 tokens; 8000 leaves a safety margin.
# Longer chunks are truncated before sending — the full text stays in
# chunks.json and still works for BM25.
MAX_TOKENS_PER_EMBEDDING_TEXT = 8000

# OpenAI limits per ONE embeddings request: ~300k total tokens and 2048
# texts. Batching matters: a large document failing on the last pipeline
# step would waste the already-paid vision calls.
MAX_TOKENS_PER_REQUEST = 250_000
MAX_TEXTS_PER_REQUEST = 1000

# Encoder for text-embedding-3-large; created once — it is expensive to init.
_TOKENIZER = tiktoken.get_encoding("cl100k_base")


def get_embeddings(texts: list[str]) -> tuple[list[list[float]], int]:
    """Embed a list of texts in one request.

    Returns (vectors, total_tokens). Vector order matches input order;
    total_tokens is OpenAI's actual count (for cost accounting).
    """
    client = OpenAI()
    response = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=texts,
    )
    vectors = [item.embedding for item in response.data]
    return vectors, response.usage.total_tokens


def _embed_batch(texts: list[str]) -> tuple[list[list[float]], int]:
    """get_embeddings с ретраем на серверный отказ «слишком много токенов».

    Локальный tiktoken-подсчёт может разойтись с серверным (инцидент
    2026-08-20, TP188: наш счёт ≤250k и один батч, сервер насчитал 424k —
    причина расхождения не найдена). Отказ max_tokens_per_request делит
    пачку пополам рекурсивно вместо падения документа; один текст пополам
    не делится — такой отказ пробрасываем.
    """
    try:
        return get_embeddings(texts)
    except BadRequestError as e:
        if e.code != "max_tokens_per_request" or len(texts) < 2:
            raise
        mid = len(texts) // 2
        print(f"  embeddings: server rejected {len(texts)} texts, splitting in half")
        left_vectors, left_tokens = _embed_batch(texts[:mid])
        right_vectors, right_tokens = _embed_batch(texts[mid:])
        return left_vectors + right_vectors, left_tokens + right_tokens


def build_searchable_text(chunk: dict) -> str:
    """Text to index: header + body — same logic as BM25, so the vector
    reflects both the section content and its context."""
    return " ".join(
        [
            chunk.get("document_title", ""),
            chunk.get("parent_section", ""),
            chunk.get("section_title", ""),
            chunk.get("text", ""),
        ]
    )


def build_embeddings_index(chunks: list[dict]) -> tuple[dict, int]:
    """Build the vector index for a list of chunks.

    Returns (index, total_tokens). On-disk index format:
      {"model": ..., "items": [{"chunk_id": ..., "embedding": [...]}, ...]}
    """
    if not chunks:
        raise ValueError("No chunks to index — the document has no extractable text.")

    texts = [build_searchable_text(chunk) for chunk in chunks]

    # Defensive truncation for chunks that exceed the model limit.
    token_counts: list[int] = []
    for i, text in enumerate(texts):
        token_ids = _TOKENIZER.encode(text)
        if len(token_ids) > MAX_TOKENS_PER_EMBEDDING_TEXT:
            print(
                f"  [!] {chunks[i]['chunk_id']}: {len(token_ids)} tokens > "
                f"{MAX_TOKENS_PER_EMBEDDING_TEXT}, truncating for embedding"
            )
            token_ids = token_ids[:MAX_TOKENS_PER_EMBEDDING_TEXT]
            texts[i] = _TOKENIZER.decode(token_ids)
        token_counts.append(len(token_ids))

    # Split into batches under the per-request limits (order preserved).
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

    # Диагностика всегда: при расхождении нашего счёта с серверным
    # (см. _embed_batch) обе цифры должны быть видны в app.log рядом.
    print(
        f"  embeddings: {len(texts)} texts, ~{sum(token_counts)} tokens "
        f"(local count), {len(batches)} batch(es)"
    )

    embeddings: list[list[float]] = []
    tokens = 0
    for n, batch in enumerate(batches, start=1):
        if len(batches) > 1:
            print(f"  embeddings: batch {n}/{len(batches)} ({len(batch)} texts)")
        vectors, used = _embed_batch(batch)
        embeddings.extend(vectors)
        tokens += used

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
    """Turn on-disk items into an in-memory matrix index for fast search.

    On disk embeddings are lists of floats. Keeping them that way is
    memory-hungry (gigabytes at 30k chunks) and slow to search (a Python
    loop). Instead all vectors go into one float32 matrix (N, D) with
    L2-normalized rows — cosine similarity against a normalized query is
    then a single matrix multiplication.

    In-memory format:
      {"model": ..., "chunk_ids": [...], "matrix": np.ndarray (N, D)}
    """
    chunk_ids = [item["chunk_id"] for item in items]
    matrix = np.asarray([item["embedding"] for item in items], dtype=np.float32)

    if matrix.size:
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0  # zero vectors: avoid division by zero
        matrix /= norms

    return {"model": model, "chunk_ids": chunk_ids, "matrix": matrix}


def search_embeddings(
    index: dict,
    query: str,
    top_k: int = 5,
) -> list[tuple[str, float]]:
    """Search the matrix index; returns (chunk_id, score) by similarity."""
    # The query is embedded with the CURRENT model — the index must use the
    # same one, otherwise we get a dimension error or silently meaningless
    # search (after changing EMBEDDING_MODEL without re-indexing).
    if index.get("model") != EMBEDDING_MODEL:
        raise RuntimeError(
            f"Index was built with {index.get('model')}, search uses "
            f"{EMBEDDING_MODEL}. Re-index the documents."
        )
    matrix = index["matrix"]
    chunk_ids = index["chunk_ids"]
    if matrix.shape[0] == 0:
        return []

    # Token cost of embedding one query is negligible — ignored.
    vectors, _ = get_embeddings([query])
    query_vec = np.asarray(vectors[0], dtype=np.float32)
    norm = np.linalg.norm(query_vec)
    if norm != 0:
        query_vec /= norm

    # Rows and query are normalized → dot product = cosine similarity.
    scores = matrix @ query_vec

    # top_k without a full sort: argpartition brings the k best forward in
    # O(N), then only those k are sorted.
    k = min(top_k, scores.shape[0])
    top_idx = np.argpartition(-scores, k - 1)[:k]
    top_idx = top_idx[np.argsort(-scores[top_idx])]
    return [(chunk_ids[i], float(scores[i])) for i in top_idx]
