"""Audit #2: an orphan vector must not fail a question with HTTP 500.

If embeddings.json lags behind chunks.json (a crash between two saves, a
machine race on a network folder), vector search returns a chunk_id absent
from the chunks — this used to raise KeyError on every question across the
whole library until someone found and reindexed the broken document.
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
    """A clean in-memory SQLite per test."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def test_orphan_embedding_id_skipped_not_500(db, monkeypatch):
    chunks = [{"chunk_id": "doc1_c001", "document_id": "doc1", "text": "beton"}]
    index = {
        "model": "test-model",
        "chunk_ids": ["doc1_c001", "doc1_c999"],  # c999 is the orphan
        "matrix": np.zeros((2, 3), dtype=np.float32),
    }
    tokens = {"doc1_c001": ["beton"]}
    monkeypatch.setattr(
        library_cache, "get_library_with_tokens", lambda: (chunks, index, tokens)
    )
    # Search returns both the live id and the orphan — like real vector
    # search over an out-of-sync index.
    monkeypatch.setattr(
        service,
        "search_by_mode",
        lambda bm25, index, query, mode: ["doc1_c001", "doc1_c999"],
    )
    monkeypatch.setattr(service, "track_event", lambda name, **props: None)
    answered: list[list[dict]] = []

    def fake_answer(
        question, top_chunks, model, page_images=None, answer_language="cs"
    ):
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
    # The orphan is dropped, the live chunk reached answer generation.
    assert [c["chunk_id"] for c in answered[0]] == ["doc1_c001"]
