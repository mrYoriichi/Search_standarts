"""Tests guarding document operations during indexing.

Delete/reindex/relink of a working document used to race: the background
pipeline finished writing artifacts after the rmtree, and the next scan
"adopted" the deleted document back (vision paid twice).
"""

import json
import time

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.core import index_lock, index_store
from backend.core.database import Base
from backend.modules.documents import service
from backend.modules.documents.models import Document


@pytest.fixture
def db():
    """A clean in-memory SQLite per test."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _add_doc(db, slug: str, status: str) -> Document:
    doc = Document(slug=slug, title=slug, status=status)
    db.add(doc)
    db.commit()
    return doc


def test_delete_processing_refused(db):
    _add_doc(db, "norma", "processing")
    with pytest.raises(service.DocumentBusyError):
        service.delete_document(db, "norma")
    # The document is still in the DB — nothing was deleted.
    assert db.scalar(select(Document).where(Document.slug == "norma")) is not None


def test_delete_ready_works(db):
    _add_doc(db, "norma", "ready")
    service.delete_document(db, "norma")
    assert db.scalar(select(Document).where(Document.slug == "norma")) is None


def test_reindex_processing_refused(db):
    _add_doc(db, "norma", "processing")
    with pytest.raises(service.DocumentBusyError):
        service.reindex_document(db, "norma", paths=[], executor=None)


def test_relink_processing_refused(db):
    _add_doc(db, "stare", "processing")
    with pytest.raises(service.DocumentBusyError):
        service.relink_document(db, "stare", "nove")


def _make_library(tmp_path, filename_slug: str):
    """A library folder with meta and one document's artifacts.

    Returns (folder, the document's scoped slug).
    """
    library = tmp_path / "lib"
    library.mkdir()
    index_store.ensure_meta(library, "test-model")
    fid = index_store.read_meta(library)["folder_id"]
    slug = index_store.scoped_slug(fid, filename_slug)
    artifacts = index_store.doc_dir(library, slug)
    artifacts.mkdir(parents=True)
    (artifacts / "chunks.json").write_text("[]", encoding="utf-8")
    return library, slug


def _make_locked_library(tmp_path, filename_slug: str, lock_age: float = 0.0):
    """Same, plus a FOREIGN lock.

    lock_age — lock age in seconds (0 = fresh, another machine is
    indexing right now).
    """
    library, slug = _make_library(tmp_path, filename_slug)
    lock_path = index_store.index_root(library) / index_lock.LOCK_FILENAME
    lock_path.write_text(
        json.dumps({"owner": "PC-KOLEGA", "ts": time.time() - lock_age}),
        encoding="utf-8",
    )
    return library, slug


def test_delete_refused_when_foreign_lock(db, tmp_path):
    # Audit #4: another machine is indexing the folder — an rmtree from
    # under it would crash its pipeline (paid vision lost).
    library, slug = _make_locked_library(tmp_path, "norma")
    _add_doc(db, slug, "ready")

    with pytest.raises(service.DocumentBusyError):
        service.delete_document(db, slug, paths=[library])

    assert db.scalar(select(Document).where(Document.slug == slug)) is not None
    assert index_store.doc_dir(library, slug).exists()


def test_relink_refused_when_foreign_lock(db, tmp_path):
    library, old_slug = _make_locked_library(tmp_path, "stare")
    _add_doc(db, old_slug, "ready")
    fid = index_store.folder_id_of(old_slug)
    new_slug = index_store.scoped_slug(fid, "nove")

    with pytest.raises(service.DocumentBusyError):
        service.relink_document(db, old_slug, new_slug, paths=[library])

    # Nothing renamed, the slug in the DB is unchanged.
    assert index_store.doc_dir(library, old_slug).exists()
    assert db.scalar(select(Document).where(Document.slug == old_slug)) is not None


@pytest.mark.parametrize(
    "bad_slug",
    ["../escaped", "..", "sub/child", "/tmp/abs", "back\\slash", "dot.name", ""],
)
def test_relink_rejects_unsafe_slug(db, tmp_path, bad_slug):
    """new_slug comes from the client and must never work as a path.

    Audit 2026-08-06 #1: `old_dir.parent / new_slug` accepted `../..` and
    absolute paths, so the paid index left .search_index — and the
    poisoned slug in the DB then aimed the rmtree of delete/reindex at a
    folder outside the library (decision #16: user files are never touched).
    """
    library, old_slug = _make_library(tmp_path, "stare")
    _add_doc(db, old_slug, "ready")

    with pytest.raises(ValueError):
        service.relink_document(db, old_slug, bad_slug, paths=[library])

    # Nothing moved, the slug in the DB is unchanged.
    assert index_store.doc_dir(library, old_slug).exists()
    assert db.scalar(select(Document).where(Document.slug == old_slug)) is not None


def test_relink_valid_slug_works(db, tmp_path):
    """The guard must not break the normal rename flow."""
    library, old_slug = _make_library(tmp_path, "stare")
    _add_doc(db, old_slug, "ready")
    new_slug = index_store.scoped_slug(index_store.folder_id_of(old_slug), "nove")

    service.relink_document(db, old_slug, new_slug, paths=[library])

    assert index_store.doc_dir(library, new_slug).exists()
    assert not index_store.doc_dir(library, old_slug).exists()
    assert db.scalar(select(Document).where(Document.slug == new_slug)) is not None


def test_delete_works_when_lock_stale(db, tmp_path):
    # A stale lock (the machine crashed) is no reason to block deletion.
    library, slug = _make_locked_library(
        tmp_path, "norma", lock_age=index_lock.TTL_SECONDS + 1
    )
    _add_doc(db, slug, "ready")

    service.delete_document(db, slug, paths=[library])

    assert db.scalar(select(Document).where(Document.slug == slug)) is None
    assert not index_store.doc_dir(library, slug).exists()
