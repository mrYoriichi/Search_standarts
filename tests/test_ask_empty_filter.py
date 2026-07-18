"""Пустая выборка документов не должна ронять вопрос 500-й ошибкой.

Фронт может прислать устаревшие document_ids (документ удалили/переименовали,
пока вкладка была открыта). Раньше пустой корпус доходил до BM25Okapi([]) и
падал ZeroDivisionError → HTTP 500 без объяснений.
"""

import numpy as np
import pytest

from backend.core import library_cache
from backend.modules.queries import service


def test_stale_document_ids_raise_clear_error(monkeypatch):
    chunks = [{"chunk_id": "doc1_c001", "document_id": "doc1", "text": "beton"}]
    index = {
        "model": "test-model",
        "chunk_ids": ["doc1_c001"],
        "matrix": np.zeros((1, 3), dtype=np.float32),
    }
    tokens = {"doc1_c001": ["beton"]}
    monkeypatch.setattr(
        library_cache, "get_library_with_tokens", lambda: (chunks, index, tokens)
    )

    with pytest.raises(service.NoSearchableDocumentsError):
        service.ask("dotaz", ["smazany_doc"], db=None, expand=False)
