"""Mixed embedding models must fail loudly, not silently break search.

The broad `except RuntimeError` in library_cache._load_merged used to
swallow model incompatibility WITHIN one root — the folder silently
dropped out of search.
"""

from pathlib import Path

import pytest

from backend.core import ui_messages

from backend.core import library_cache
from common.jsonio import save_json_atomic


@pytest.fixture(autouse=True)
def czech_messages():
    """Test texts are the Czech references; the app default is English now."""
    ui_messages.set_language("cs")
    yield
    ui_messages.set_language("en")


def _make_doc(root: Path, slug: str, model: str, dim: int) -> None:
    """A ready document in the root: chunks.json + embeddings.json of a given model."""
    doc_dir = root / slug
    doc_dir.mkdir(parents=True)
    save_json_atomic(
        doc_dir / "chunks.json",
        [{"chunk_id": f"{slug}_c001", "document_id": slug, "text": "beton"}],
    )
    save_json_atomic(
        doc_dir / "embeddings.json",
        {
            "model": model,
            "items": [{"chunk_id": f"{slug}_c001", "embedding": [0.1] * dim}],
        },
    )


@pytest.fixture
def isolated_cache(tmp_path, monkeypatch):
    """Disables the real pools and clears the module-global cache around the test."""
    monkeypatch.setattr(library_cache, "PROJECTS_DATA_DIR", tmp_path / "no_projects")
    library_cache.invalidate()
    yield
    library_cache.invalidate()


def test_mixed_models_in_one_folder_fail_loudly(tmp_path, monkeypatch, isolated_cache):
    mixed = tmp_path / "root"
    _make_doc(mixed, "doc_a", "model-a", 2)
    _make_doc(mixed, "doc_b", "model-b", 3)
    monkeypatch.setattr(library_cache, "_shared_index_roots", lambda: [mixed])

    with pytest.raises(RuntimeError, match="jiným modelem"):
        library_cache._load_merged()


def test_pools_on_different_models_fail_loudly(tmp_path, monkeypatch, isolated_cache):
    """Two roots, each internally consistent, but models differ — a loud error."""
    root_a = tmp_path / "root_a"
    root_b = tmp_path / "root_b"
    _make_doc(root_a, "doc_a", "model-a", 2)
    _make_doc(root_b, "doc_b", "model-b", 2)
    monkeypatch.setattr(library_cache, "_shared_index_roots", lambda: [root_a, root_b])

    with pytest.raises(RuntimeError, match="různými modely"):
        library_cache._load_merged()


def test_empty_roots_raise_czech_message(tmp_path, monkeypatch, isolated_cache):
    """No ready documents anywhere — the Czech UI error (not a regression)."""
    monkeypatch.setattr(library_cache, "_shared_index_roots", lambda: [])

    with pytest.raises(RuntimeError, match="hotový dokument"):
        library_cache._load_merged()
