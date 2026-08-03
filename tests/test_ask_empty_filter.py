"""An empty document selection must not fail the question with a 500.

The frontend may send stale document_ids (a document deleted/renamed while
the tab was open). An empty corpus used to reach BM25Okapi([]) and crash
with ZeroDivisionError -> HTTP 500 with no explanation.
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
