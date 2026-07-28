"""Смешанные embedding-модели должны падать громко, а не молча ронять поиск.

Раньше широкий `except RuntimeError` в library_cache._load_merged глотал
несовместимость моделей ВНУТРИ одного корня — папка молча выпадала из поиска.
"""

from pathlib import Path

import pytest

from backend.core import library_cache
from jsonio import save_json_atomic


def _make_doc(root: Path, slug: str, model: str, dim: int) -> None:
    """Готовый документ в корне: chunks.json + embeddings.json заданной модели."""
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
    """Отключает реальные пулы и чистит module-global кеш до/после теста."""
    monkeypatch.setattr(library_cache, "DATA_ROOT", tmp_path / "no_raw")
    monkeypatch.setattr(library_cache, "PROJECTS_DATA_DIR", tmp_path / "no_projects")
    library_cache.invalidate()
    yield
    library_cache.invalidate()


def test_mixed_models_in_one_folder_fail_loudly(tmp_path, monkeypatch, isolated_cache):
    mixed = tmp_path / "root"
    _make_doc(mixed, "doc_a", "model-a", 2)
    _make_doc(mixed, "doc_b", "model-b", 3)
    monkeypatch.setattr(library_cache, "_library_index_roots", lambda: [mixed])

    with pytest.raises(RuntimeError, match="модел"):
        library_cache._load_merged()


def test_pools_on_different_models_fail_loudly(tmp_path, monkeypatch, isolated_cache):
    """Два корня, каждый внутри консистентен, но модели разные — громкая ошибка."""
    root_a = tmp_path / "root_a"
    root_b = tmp_path / "root_b"
    _make_doc(root_a, "doc_a", "model-a", 2)
    _make_doc(root_b, "doc_b", "model-b", 2)
    monkeypatch.setattr(library_cache, "_library_index_roots", lambda: [root_a, root_b])

    with pytest.raises(RuntimeError, match="разными моделями"):
        library_cache._load_merged()


def test_empty_roots_raise_czech_message(tmp_path, monkeypatch, isolated_cache):
    """Нет готовых документов нигде — чешская ошибка для UI (не regression)."""
    monkeypatch.setattr(library_cache, "_library_index_roots", lambda: [])

    with pytest.raises(RuntimeError, match="hotový dokument"):
        library_cache._load_merged()
