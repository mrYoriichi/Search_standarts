"""№2 аудита: вектор-сирота не должен ронять вопрос HTTP 500.

Если embeddings.json отстал от chunks.json (крах между двумя сохранениями,
гонка машин на сетевой папке), векторный поиск возвращает chunk_id, которого
нет среди чанков, — раньше это давало KeyError на каждый вопрос по всей
библиотеке, пока кто-нибудь не найдёт и не переиндексирует битый документ.
"""

import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.core import library_cache
from backend.core.database import Base
from backend.modules.queries import service


@pytest.fixture
def db():
    """Чистая in-memory SQLite на каждый тест."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def test_orphan_embedding_id_skipped_not_500(db, monkeypatch):
    chunks = [{"chunk_id": "doc1_c001", "document_id": "doc1", "text": "beton"}]
    index = {
        "model": "test-model",
        "chunk_ids": ["doc1_c001", "doc1_c999"],  # c999 — сирота
        "matrix": np.zeros((2, 3), dtype=np.float32),
    }
    tokens = {"doc1_c001": ["beton"]}
    monkeypatch.setattr(
        library_cache, "get_library_with_tokens", lambda: (chunks, index, tokens)
    )
    # Поиск возвращает и живой id, и сироту — как настоящий векторный поиск
    # по рассинхронизированному индексу.
    monkeypatch.setattr(
        service,
        "search_by_mode",
        lambda bm25, index, query, mode: ["doc1_c001", "doc1_c999"],
    )
    monkeypatch.setattr(service, "track_event", lambda name, **props: None)
    answered: list[list[dict]] = []

    def fake_answer(question, top_chunks, model, page_images=None):
        answered.append(top_chunks)
        return {
            "answer": "odpověď",
            "sources": [],
            "related_sources": [],
            "used_chunks": [],
            "prompt_tokens": 1,
            "completion_tokens": 1,
        }

    monkeypatch.setattr(service, "generate_answer", fake_answer)

    resp = service.ask("dotaz", None, db=db, expand=False)

    assert resp.answer == "odpověď"
    # Сирота отброшен, живой чанк дошёл до генерации ответа.
    assert [c["chunk_id"] for c in answered[0]] == ["doc1_c001"]
