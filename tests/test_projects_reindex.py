"""Tests of archive document reindexing (POST /projects/{slug}/reindex).

The 🔄 button in the archive serves the live run of step 3: former sheet
documents are reprocessed by the new shared pipeline. Mirrors
test_documents_guards.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.core.database import Base
from backend.modules.projects import service
from backend.modules.projects.models import ProjectDocument
from backend.modules.projects.pipeline import run_project_pipeline


@pytest.fixture
def db():
    """A clean in-memory SQLite per test."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _add_doc(db, slug: str, status: str) -> ProjectDocument:
    doc = ProjectDocument(
        slug=slug,
        project="Most",
        relative_path="TZ.pdf",
        doc_type="text",
        page_count=1,
        status=status,
    )
    db.add(doc)
    db.commit()
    return doc


class _FakeExecutor:
    def __init__(self):
        self.calls = []

    def submit(self, fn, *args):
        self.calls.append((fn, args))


def test_reindex_processing_refused(db):
    _add_doc(db, "most__tz", "processing")
    with pytest.raises(service.DocumentBusyError):
        service.reindex_document(db, "most__tz", paths=[], executor=None)


def test_reindex_unknown_slug_refused(db):
    with pytest.raises(ValueError):
        service.reindex_document(db, "neni", paths=[], executor=None)


def test_reindex_missing_file_refused(db, tmp_path):
    # The file is in no archive folder (network drive dropped / file deleted).
    _add_doc(db, "most__tz", "ready")
    with pytest.raises(ValueError):
        service.reindex_document(db, "most__tz", paths=[tmp_path], executor=None)


def test_reindex_error_doc_resubmits_with_fresh_stat(db, tmp_path, monkeypatch):
    monkeypatch.setattr(service, "PROJECTS_DATA_DIR", tmp_path / "projects_data")
    # The connected folder = the "Most" project itself, the PDF right in it.
    project_dir = tmp_path / "Most"
    project_dir.mkdir(parents=True)
    pdf_path = project_dir / "TZ.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")
    old_artifacts = tmp_path / "projects_data" / "most__tz"
    old_artifacts.mkdir(parents=True)
    (old_artifacts / "chunks.json").write_text("[]", encoding="utf-8")

    doc = _add_doc(db, "most__tz", "error")
    doc.error = "stará chyba"
    db.commit()

    executor = _FakeExecutor()
    result = service.reindex_document(db, "most__tz", [project_dir], executor)

    assert result.status == "processing"
    assert result.error is None
    # Contract 2026-08-02: artifacts of a failed document are NOT wiped —
    # the describe resume continues from the checkpoint without paying
    # again. The legacy local checkpoint moves into the project folder,
    # where the pipeline now reads and writes.
    assert not old_artifacts.exists()
    assert (project_dir / ".search_index" / "most__tz" / "chunks.json").exists()
    # A fresh stat is recorded — the next scan won't reset the document to pending.
    assert result.file_mtime == pytest.approx(pdf_path.stat().st_mtime)
    assert result.file_size == pdf_path.stat().st_size
    (fn, args) = executor.calls[0]
    assert fn is run_project_pipeline
    assert args == ("most__tz", str(pdf_path), str(project_dir))


def test_reindex_error_doc_keeps_artifacts(db, tmp_path, monkeypatch):
    """🔄 on a failed document continues from the checkpoint, not paying anew.

    Live case 2026-08-02: vision failed twice on page 166 of ~189 —
    rmtree was throwing away the paid descriptions of 165 pages.
    """
    monkeypatch.setattr(service, "PROJECTS_DATA_DIR", tmp_path / "pool")
    artifacts = tmp_path / "pool" / "most__tz"
    artifacts.mkdir(parents=True)
    (artifacts / "descriptions.json").write_text("{}", encoding="utf-8")
    root = tmp_path / "Most"
    root.mkdir()
    (root / "TZ.pdf").write_bytes(b"%PDF-1.4 fake")
    _add_doc(db, "most__tz", "error")

    executor = _FakeExecutor()
    service.reindex_document(db, "most__tz", [root], executor)

    # The checkpoint survives — moved into the project folder, where the
    # describe resume will pick it up.
    assert (root / ".search_index" / "most__tz" / "descriptions.json").exists()
    assert len(executor.calls) == 1


def test_reindex_ready_doc_wipes_artifacts(db, tmp_path, monkeypatch):
    """For a ready document 🔄 is an honest rebuild: artifacts are wiped."""
    monkeypatch.setattr(service, "PROJECTS_DATA_DIR", tmp_path / "pool")
    artifacts = tmp_path / "pool" / "most__tz"
    artifacts.mkdir(parents=True)
    (artifacts / "descriptions.json").write_text("{}", encoding="utf-8")
    root = tmp_path / "Most"
    root.mkdir()
    (root / "TZ.pdf").write_bytes(b"%PDF-1.4 fake")
    _add_doc(db, "most__tz", "ready")

    executor = _FakeExecutor()
    service.reindex_document(db, "most__tz", [root], executor)

    assert not artifacts.exists()
