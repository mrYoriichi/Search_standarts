"""Кеш поиска должен замечать переиндексацию общей папки ДРУГОЙ машиной.

invalidate() локален для процесса. Чужая машина переписывает embeddings.json
в общей .search_index — без проверки отпечатка mtime этот процесс отдавал бы
старые чанки до рестарта.
"""

import os
import shutil
from pathlib import Path

import pytest

from backend.core import library_cache
from jsonio import save_json_atomic


def _write_doc(root: Path, slug: str, text: str) -> None:
    doc_dir = root / slug
    doc_dir.mkdir(parents=True, exist_ok=True)
    save_json_atomic(
        doc_dir / "chunks.json",
        [{"chunk_id": f"{slug}_c001", "document_id": slug, "text": text}],
    )
    save_json_atomic(
        doc_dir / "embeddings.json",
        {
            "model": "test-model",
            "items": [{"chunk_id": f"{slug}_c001", "embedding": [1.0, 0.0]}],
        },
    )


@pytest.fixture
def shared_root(tmp_path, monkeypatch):
    """Общая папка с одним готовым документом; реальные пулы отключены."""
    root = tmp_path / "lib" / ".search_index"
    _write_doc(root, "doc", "OLD")
    monkeypatch.setattr(library_cache, "DATA_ROOT", tmp_path / "no_raw")
    monkeypatch.setattr(library_cache, "PROJECTS_DATA_DIR", tmp_path / "no_projects")
    monkeypatch.setattr(library_cache, "_library_index_roots", lambda: [root])
    library_cache.invalidate()
    yield root
    library_cache.invalidate()


def test_remote_reindex_picked_up_without_local_invalidate(shared_root):
    chunks, _ = library_cache.get_library()
    assert chunks[0]["text"] == "OLD"

    # «Другая машина»: переписывает файлы и НЕ зовёт наш invalidate().
    _write_doc(shared_root, "doc", "NEW")
    emb = shared_root / "doc" / "embeddings.json"
    st = emb.stat()
    # Явный utime: на грубых файловых системах mtime меняется раз в 1-2 с.
    os.utime(emb, ns=(st.st_atime_ns + 2_000_000_000, st.st_mtime_ns + 2_000_000_000))

    chunks, _ = library_cache.get_library()
    assert chunks[0]["text"] == "NEW"


def test_unchanged_library_reuses_cache(shared_root):
    # Без изменений на диске кеш не перечитывается (защита от чтения на каждый вопрос).
    assert library_cache.get_library() is library_cache.get_library()


def test_remote_delete_drops_doc(shared_root):
    _write_doc(shared_root, "doc2", "TWO")
    chunks, _ = library_cache.get_library()
    assert {c["document_id"] for c in chunks} == {"doc", "doc2"}

    shutil.rmtree(shared_root / "doc2")
    chunks, _ = library_cache.get_library()
    assert {c["document_id"] for c in chunks} == {"doc"}


def test_unreachable_root_keeps_serving_cache(shared_root, tmp_path):
    # Отвал сетевого диска ≠ «документы удалили»: тёплый кеш продолжает
    # отвечать полным корпусом, а не молча теряет всю общую библиотеку.
    chunks, _ = library_cache.get_library()
    assert chunks[0]["text"] == "OLD"

    hidden = tmp_path / "hidden"
    shared_root.rename(hidden)  # «диск отвалился»
    chunks, _ = library_cache.get_library()
    assert chunks[0]["text"] == "OLD"  # кеш жив, без исключений

    hidden.rename(shared_root)  # диск вернулся, файлы те же — кеш ещё жив
    chunks, _ = library_cache.get_library()
    assert chunks[0]["text"] == "OLD"

    # А реальная переиндексация после возврата — ловится.
    _write_doc(shared_root, "doc", "NEW")
    emb = shared_root / "doc" / "embeddings.json"
    st = emb.stat()
    os.utime(emb, ns=(st.st_atime_ns + 2_000_000_000, st.st_mtime_ns + 2_000_000_000))
    chunks, _ = library_cache.get_library()
    assert chunks[0]["text"] == "NEW"
