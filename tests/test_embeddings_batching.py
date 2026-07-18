"""Тесты батчинга эмбеддингов: большой документ шлётся партиями, не одним запросом."""

import pytest

from indexing import embeddings_index


def _install_fake(monkeypatch, calls: list[list[str]]):
    """Подменяет get_embeddings: записывает партии, возвращает фиктивные векторы."""

    def fake(texts: list[str]) -> tuple[list[list[float]], int]:
        calls.append(list(texts))
        return [[0.1, 0.2] for _ in texts], len(texts)

    monkeypatch.setattr(embeddings_index, "get_embeddings", fake)


def _chunks(n: int) -> list[dict]:
    return [{"chunk_id": f"c{i:03d}", "text": "beton most pilíř"} for i in range(n)]


def test_empty_chunks_raise_clear_error():
    # Раньше пустой список уезжал в OpenAI и падал криптоошибкой 400.
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
    # Порядок chunk_id не пострадал от разбиения.
    assert [it["chunk_id"] for it in index["items"]] == [f"c{i:03d}" for i in range(5)]


def test_batches_respect_token_limit(monkeypatch):
    calls: list[list[str]] = []
    _install_fake(monkeypatch, calls)
    # Каждый текст — несколько токенов; лимит 10 заставит разбить на партии.
    monkeypatch.setattr(embeddings_index, "MAX_TOKENS_PER_REQUEST", 10)
    index, _ = embeddings_index.build_embeddings_index(_chunks(6))
    assert len(calls) > 1
    assert sum(len(c) for c in calls) == 6
    assert len(index["items"]) == 6
