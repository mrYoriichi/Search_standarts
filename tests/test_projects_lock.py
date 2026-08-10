"""The inter-machine folder lock guards archive indexing (mirrors the library).

Two machines indexing one shared project folder at once would pay vision
twice and race writes in .search_index — the folder is locked with
index.lock, exactly like a library folder.
"""

import json
import time
from pathlib import Path

import pypdfium2 as pdfium
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.core import index_lock, index_store
from backend.core.database import Base
from backend.modules.projects import service
from backend.modules.projects.models import ProjectDocument
from backend.modules.settings import models as settings_models  # noqa: F401 — settings table for create_all
from backend.modules.projects.service import (
    make_project_slug,
    start_archive_indexing,
    sync_archive,
)


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


def _make_pdf(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = pdfium.PdfDocument.new()
    doc.new_page(595, 842)
    doc.save(path)
    doc.close()


def _foreign_lock(root: Path) -> None:
    index_store.index_root(root).mkdir(parents=True, exist_ok=True)
    lock = index_store.index_root(root) / "index.lock"
    lock.write_text(
        json.dumps({"owner": "kolegova-masina", "ts": time.time()}),
        encoding="utf-8",
    )


class _FakeExecutor:
    def __init__(self):
        self.calls = []

    def submit(self, fn, *args):
        self.calls.append((fn, args))


def test_index_skips_folder_locked_by_another_machine(db, artifacts_dir, tmp_path):
    root = tmp_path / "Most"
    _make_pdf(root / "tz.pdf")
    slug = make_project_slug("Most", "tz.pdf")
    sync_archive(db, [root])
    _foreign_lock(root)

    executor = _FakeExecutor()
    submitted, locked = start_archive_indexing(db, [root], executor)

    doc = db.scalar(select(ProjectDocument).where(ProjectDocument.slug == slug))
    assert submitted == 0
    assert executor.calls == []
    assert doc.status == "pending"  # left for a later run, not lost
    assert locked == ["Most: kolegova-masina"]


def test_index_takes_the_folder_lock(db, artifacts_dir, tmp_path):
    root = tmp_path / "Most"
    _make_pdf(root / "tz.pdf")
    sync_archive(db, [root])

    submitted, locked = start_archive_indexing(db, [root], _FakeExecutor())

    assert submitted == 1
    assert locked == []
    lock = index_lock.read_lock(root)
    assert lock is not None and lock["owner"] == index_lock.owner()
    index_lock.done(root)  # release: the fake executor never runs the pipeline


def test_pipeline_releases_lock_when_done(db, artifacts_dir, tmp_path, monkeypatch):
    # The real launch chain: start_archive_indexing takes the lock, the
    # pipeline (run in a thread) must release it after the last document.
    from sqlalchemy.orm import sessionmaker as sm

    from backend.core import parse_subprocess
    from backend.modules.projects import pipeline
    from pipeline import chunk, describe, embed

    root = tmp_path / "Most"
    _make_pdf(root / "tz.pdf")
    sync_archive(db, [root])
    engine = db.get_bind()
    monkeypatch.setattr(pipeline, "SessionLocal", sm(bind=engine))
    monkeypatch.setattr(parse_subprocess, "run_parse", lambda *a, **k: None)
    monkeypatch.setattr(describe, "process", lambda *a, **k: None)

    def fake_chunk(pdf_name, doc_dir=None):
        doc_dir.mkdir(parents=True, exist_ok=True)
        (doc_dir / "chunks.json").write_text("[]", encoding="utf-8")

    monkeypatch.setattr(chunk, "process", fake_chunk)
    monkeypatch.setattr(embed, "process", lambda *a, **k: None)

    executor = _FakeExecutor()
    start_archive_indexing(db, [root], executor)
    assert index_lock.read_lock(root) is not None

    (fn, args) = executor.calls[0]
    fn(*args)  # what the executor thread would do

    assert index_lock.read_lock(root) is None  # the last document released it


def test_reindex_refuses_foreign_lock(db, artifacts_dir, tmp_path):
    root = tmp_path / "Most"
    _make_pdf(root / "tz.pdf")
    slug = make_project_slug("Most", "tz.pdf")
    sync_archive(db, [root])
    doc = db.scalar(select(ProjectDocument).where(ProjectDocument.slug == slug))
    doc.status = "ready"
    db.commit()
    _foreign_lock(root)

    with pytest.raises(service.DocumentBusyError):
        service.reindex_document(db, slug, [root], _FakeExecutor())

    db.refresh(doc)
    assert doc.status == "ready"  # untouched
