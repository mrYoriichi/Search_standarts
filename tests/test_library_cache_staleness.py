"""The search cache must notice a shared folder reindexed by ANOTHER machine.

invalidate() is process-local. The other machine rewrites embeddings.json in
the shared .search_index — without the mtime fingerprint check this process
would serve stale chunks until a restart.
"""

import os
import shutil
from pathlib import Path

import pytest

from backend.core import library_cache
from common.jsonio import save_json_atomic


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
    """A shared folder with one ready document; real pools disabled."""
    root = tmp_path / "lib" / ".search_index"
    _write_doc(root, "doc", "OLD")
    monkeypatch.setattr(library_cache, "PROJECTS_DATA_DIR", tmp_path / "no_projects")
    monkeypatch.setattr(library_cache, "_library_index_roots", lambda: [root])
    # TTL=0: the tests above check the fingerprint mechanism itself, no throttling.
    monkeypatch.setattr(library_cache, "_FINGERPRINT_TTL_S", 0.0)
    library_cache.invalidate()
    yield root
    library_cache.invalidate()


def test_remote_reindex_picked_up_without_local_invalidate(shared_root):
    chunks, _ = library_cache.get_library()
    assert chunks[0]["text"] == "OLD"

    # "The other machine": rewrites files and does NOT call our invalidate().
    _write_doc(shared_root, "doc", "NEW")
    emb = shared_root / "doc" / "embeddings.json"
    st = emb.stat()
    # Explicit utime: on coarse file systems mtime changes once per 1-2 s.
    os.utime(emb, ns=(st.st_atime_ns + 2_000_000_000, st.st_mtime_ns + 2_000_000_000))

    chunks, _ = library_cache.get_library()
    assert chunks[0]["text"] == "NEW"


def test_unchanged_library_reuses_cache(shared_root):
    # Without disk changes the cache is not re-read (guards against per-question reads).
    assert library_cache.get_library() is library_cache.get_library()


def test_remote_delete_drops_doc(shared_root):
    _write_doc(shared_root, "doc2", "TWO")
    chunks, _ = library_cache.get_library()
    assert {c["document_id"] for c in chunks} == {"doc", "doc2"}

    shutil.rmtree(shared_root / "doc2")
    chunks, _ = library_cache.get_library()
    assert {c["document_id"] for c in chunks} == {"doc"}


def test_unreachable_root_keeps_serving_cache(shared_root, tmp_path):
    # A dropped network drive != "documents deleted": the warm cache keeps
    # answering with the full corpus instead of silently losing the library.
    chunks, _ = library_cache.get_library()
    assert chunks[0]["text"] == "OLD"

    hidden = tmp_path / "hidden"
    shared_root.rename(hidden)  # "the drive dropped"
    chunks, _ = library_cache.get_library()
    assert chunks[0]["text"] == "OLD"  # cache alive, no exceptions

    hidden.rename(shared_root)  # drive back, same files — cache still alive
    chunks, _ = library_cache.get_library()
    assert chunks[0]["text"] == "OLD"

    # And a real reindex after the return is caught.
    _write_doc(shared_root, "doc", "NEW")
    emb = shared_root / "doc" / "embeddings.json"
    st = emb.stat()
    os.utime(emb, ns=(st.st_atime_ns + 2_000_000_000, st.st_mtime_ns + 2_000_000_000))
    chunks, _ = library_cache.get_library()
    assert chunks[0]["text"] == "NEW"


def test_fingerprint_throttled_between_questions(shared_root, monkeypatch):
    # On a network folder the stat sweep costs 0.2-10 s — within the TTL the
    # fingerprint is not recomputed (a minute's delay for foreign changes is
    # fine). Local changes go through invalidate() and bypass the throttle.
    monkeypatch.setattr(library_cache, "_FINGERPRINT_TTL_S", 3600.0)
    chunks, _ = library_cache.get_library()
    assert chunks[0]["text"] == "OLD"

    _write_doc(shared_root, "doc", "NEW")
    emb = shared_root / "doc" / "embeddings.json"
    st = emb.stat()
    os.utime(emb, ns=(st.st_atime_ns + 2_000_000_000, st.st_mtime_ns + 2_000_000_000))

    chunks, _ = library_cache.get_library()
    assert chunks[0]["text"] == "OLD"  # within TTL — no sweep, cache as is

    library_cache.invalidate()  # a local mutation resets the TTL too
    chunks, _ = library_cache.get_library()
    assert chunks[0]["text"] == "NEW"
