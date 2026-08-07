"""Adoption of ready archive indexes at scan time (mirrors the library).

A colleague indexed the shared project folder (or the folder was copied
from another computer) — its .search_index already holds complete
artifacts. The scan registers such documents as ready at no cost instead
of asking for a paid indexing run.
"""

from pathlib import Path

import pypdfium2 as pdfium
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.core import index_store
from backend.core.database import Base
from backend.core.ui_messages import msg
from backend.modules.projects import service
from backend.modules.projects.models import ProjectDocument
from backend.modules.projects.service import (
    make_project_slug,
    start_archive_indexing,
    sync_archive,
)
from common.jsonio import save_json_atomic
from indexing.embeddings_index import EMBEDDING_MODEL


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture
def artifacts_dir(tmp_path, monkeypatch):
    pool = tmp_path / "projects_data"
    pool.mkdir()
    monkeypatch.setattr(service, "PROJECTS_DATA_DIR", pool)
    return pool


def _make_pdf(path: Path, pages: int = 1) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = pdfium.PdfDocument.new()
    for _ in range(pages):
        doc.new_page(595, 842)
    doc.save(path)
    doc.close()


def _write_index(doc_dir: Path, slug: str) -> None:
    doc_dir.mkdir(parents=True, exist_ok=True)
    save_json_atomic(
        doc_dir / "chunks.json",
        [{"chunk_id": f"{slug}_c000", "document_id": slug, "text": "obsah"}],
    )
    save_json_atomic(
        doc_dir / "embeddings.json",
        {
            "model": EMBEDDING_MODEL,
            "items": [{"chunk_id": f"{slug}_c000", "embedding": [1.0, 0.0]}],
        },
    )


def _write_meta(root: Path, model: str = EMBEDDING_MODEL) -> None:
    index_store.index_root(root).mkdir(parents=True, exist_ok=True)
    save_json_atomic(
        index_store.index_root(root) / "meta.json",
        {"format_version": 1, "folder_id": "f1", "embedding_model": model},
    )


class _FakeExecutor:
    def __init__(self):
        self.calls = []

    def submit(self, fn, *args):
        self.calls.append((fn, args))


def test_scan_adopts_ready_index(db, artifacts_dir, tmp_path):
    # Second computer: the folder arrives with complete indexes inside.
    root = tmp_path / "Most"
    _make_pdf(root / "tz.pdf")
    slug = make_project_slug("Most", "tz.pdf")
    _write_meta(root)
    _write_index(index_store.doc_dir(root, slug), slug)

    summary = sync_archive(db, [root])

    doc = db.scalar(select(ProjectDocument).where(ProjectDocument.slug == slug))
    assert doc.status == "ready"
    assert summary.adopted == 1
    assert summary.new == 0


def test_scan_foreign_model_not_adopted(db, artifacts_dir, tmp_path):
    # Indexes built with another embedding model are incomparable with
    # ours — the document must go through a paid run instead.
    root = tmp_path / "Most"
    _make_pdf(root / "tz.pdf")
    slug = make_project_slug("Most", "tz.pdf")
    _write_meta(root, model="cizi-model")
    _write_index(index_store.doc_dir(root, slug), slug)

    summary = sync_archive(db, [root])

    doc = db.scalar(select(ProjectDocument).where(ProjectDocument.slug == slug))
    assert doc.status == "pending"
    assert summary.adopted == 0
    assert summary.new == 1


def test_scan_incomplete_index_not_adopted(db, artifacts_dir, tmp_path):
    root = tmp_path / "Most"
    _make_pdf(root / "tz.pdf")
    slug = make_project_slug("Most", "tz.pdf")
    _write_meta(root)
    doc_dir = index_store.doc_dir(root, slug)
    doc_dir.mkdir(parents=True)
    (doc_dir / "chunks.json").write_text("[]", encoding="utf-8")  # no embeddings

    summary = sync_archive(db, [root])

    doc = db.scalar(select(ProjectDocument).where(ProjectDocument.slug == slug))
    assert doc.status == "pending"
    assert summary.adopted == 0


def test_indexovat_adopts_pending_without_paying(db, artifacts_dir, tmp_path):
    # The document was registered as pending BEFORE the colleague's index
    # appeared: "Indexovat" re-checks the folder and adopts for free.
    root = tmp_path / "Most"
    _make_pdf(root / "tz.pdf")
    slug = make_project_slug("Most", "tz.pdf")
    sync_archive(db, [root])
    _write_meta(root)
    _write_index(index_store.doc_dir(root, slug), slug)

    executor = _FakeExecutor()
    submitted = start_archive_indexing(db, [root], executor)

    doc = db.scalar(select(ProjectDocument).where(ProjectDocument.slug == slug))
    assert doc.status == "ready"
    assert executor.calls == []
    assert submitted == 0


def test_scan_readonly_folder_marks_new_docs(db, artifacts_dir, tmp_path):
    # .search_index cannot be created (read-only folder; here the name is
    # taken by a file) — instead of an eternal silent "čeká" the document
    # fails with a clear reason.
    root = tmp_path / "Most"
    _make_pdf(root / "tz.pdf")
    (root / ".search_index").write_text("not a folder", encoding="utf-8")

    sync_archive(db, [root])

    doc = db.scalar(select(ProjectDocument))
    assert doc.status == "error"
    assert doc.error == msg("lib.readonly_folder")
