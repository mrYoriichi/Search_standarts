"""Embedding batching tests: a large document is sent in batches, not one request."""

import numpy as np
import pytest

from indexing import embeddings_index


def _install_fake(monkeypatch, calls: list[list[str]]):
    """Replaces get_embeddings: records the batches, returns fake vectors."""

    def fake(texts: list[str]) -> tuple[list[list[float]], int]:
        calls.append(list(texts))
        return [[0.1, 0.2] for _ in texts], len(texts)

    monkeypatch.setattr(embeddings_index, "get_embeddings", fake)


def _chunks(n: int) -> list[dict]:
    return [{"chunk_id": f"c{i:03d}", "text": "beton most pilíř"} for i in range(n)]


def test_empty_chunks_raise_clear_error():
    # An empty list used to go to OpenAI and fail with a cryptic 400.
    with pytest.raises(ValueError):
        embeddings_index.build_embeddings_index([])


def test_small_doc_goes_in_one_request(monkeypatch):
    calls: list[list[str]] = []
    _install_fake(monkeypatch, calls)
    index, _ = embeddings_index.build_embeddings_index(_chunks(5))
    assert len(calls) == 1
    assert len(index["items"]) == 5


def test_batches_respect_count_limit(monkeypatch):
    calls: list[list[str]] = []
    _install_fake(monkeypatch, calls)
    monkeypatch.setattr(embeddings_index, "MAX_TEXTS_PER_REQUEST", 2)
    index, _ = embeddings_index.build_embeddings_index(_chunks(5))
    assert [len(c) for c in calls] == [2, 2, 1]
    # The chunk_id order is unharmed by the split.
    assert [it["chunk_id"] for it in index["items"]] == [f"c{i:03d}" for i in range(5)]


def test_search_rejects_foreign_model_index():
    # Changing EMBEDDING_MODEL without reindexing — a clear error, not garbage.
    index = {
        "model": "stary-model",
        "chunk_ids": [],
        "matrix": np.zeros((0, 3), dtype=np.float32),
    }
    with pytest.raises(RuntimeError):
        embeddings_index.search_embeddings(index, "dotaz")


def test_batches_respect_token_limit(monkeypatch):
    calls: list[list[str]] = []
    _install_fake(monkeypatch, calls)
    # Each text is a few tokens; a limit of 10 forces splitting into batches.
    monkeypatch.setattr(embeddings_index, "MAX_TOKENS_PER_REQUEST", 10)
    index, _ = embeddings_index.build_embeddings_index(_chunks(6))
    assert len(calls) > 1
    assert sum(len(c) for c in calls) == 6
    assert len(index["items"]) == 6


def _token_reject(n_texts: int) -> Exception:
    """Серверный отказ «слишком много токенов в запросе» (код OpenAI)."""
    import httpx
    from openai import BadRequestError

    return BadRequestError(
        f"Requested too many tokens for {n_texts} texts",
        response=httpx.Response(400, request=httpx.Request("POST", "https://x")),
        body={"code": "max_tokens_per_request"},
    )


def test_server_token_reject_splits_batch(monkeypatch):
    """Сервер считает токены сам; его отказ делит пачку пополам и повторяет.

    Инцидент 2026-08-20 (TP188): локальный счёт дал ≤250k и один батч,
    сервер насчитал 424k и отбил запрос — документ падал целиком.
    """
    calls: list[list[str]] = []

    def fake(texts: list[str]) -> tuple[list[list[float]], int]:
        calls.append(list(texts))
        if len(texts) > 2:  # «серверный» лимит, о котором наш счётчик не знает
            raise _token_reject(len(texts))
        return [[0.1, 0.2] for _ in texts], len(texts)

    monkeypatch.setattr(embeddings_index, "get_embeddings", fake)
    index, _ = embeddings_index.build_embeddings_index(_chunks(5))
    # Все 5 чанков обработаны, порядок цел: 5 → (2, 3) → 3 → (1, 2).
    assert [it["chunk_id"] for it in index["items"]] == [f"c{i:03d}" for i in range(5)]
    assert [len(c) for c in calls] == [5, 2, 3, 1, 2]


def test_other_bad_request_propagates(monkeypatch):
    """Чужие 400 (не про токены) не глотаем — пусть падают как раньше."""
    import httpx
    from openai import BadRequestError

    def fake(texts: list[str]):
        raise BadRequestError(
            "invalid",
            response=httpx.Response(400, request=httpx.Request("POST", "https://x")),
            body={"code": "invalid_api_key"},
        )

    monkeypatch.setattr(embeddings_index, "get_embeddings", fake)
    with pytest.raises(BadRequestError):
        embeddings_index.build_embeddings_index(_chunks(3))


def test_single_text_reject_propagates(monkeypatch):
    """Один текст пополам не делится — отказ уходит наверх, не в бесконечный цикл."""

    def fake(texts: list[str]):
        raise _token_reject(len(texts))

    monkeypatch.setattr(embeddings_index, "get_embeddings", fake)
    from openai import BadRequestError

    with pytest.raises(BadRequestError):
        embeddings_index.build_embeddings_index(_chunks(1))
