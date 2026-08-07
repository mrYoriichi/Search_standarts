"""Archive artifacts live inside the project folder (<root>/.search_index/).

Mirrors the library (stage 4): indexes travel with the folder — copy the
project folder to another computer or share it over the network and the
paid index goes along. The local projects_data pool remains only as a
legacy location; complete artifacts migrate into the folder on scan.
"""

from pathlib import Path

import pypdfium2 as pdfium
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.core import index_store
from backend.core.database import Base
from backend.modules.projects import service
from backend.modules.projects.models import ProjectDocument
from backend.modules.projects.pipeline import run_project_pipeline
from backend.modules.projects.service import (
    make_project_slug,
    start_archive_indexing,
    sync_archive,
)
from common.jsonio import save_json_atomic


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture
def artifacts_dir(tmp_path, monkeypatch):
    """The legacy local pool (projects_data), patched into the service."""
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
    """A complete artifact pair (chunks + embeddings) for one document."""
    doc_dir.mkdir(parents=True, exist_ok=True)
    save_json_atomic(
        doc_dir / "chunks.json",
        [{"chunk_id": f"{slug}_c000", "document_id": slug, "text": "obsah"}],
    )
    save_json_atomic(
        doc_dir / "embeddings.json",
        {
            "model": "test-model",
            "items": [{"chunk_id": f"{slug}_c000", "embedding": [1.0, 0.0]}],
        },
    )


class _FakeExecutor:
    def __init__(self):
        self.calls = []

    def submit(self, fn, *args):
        self.calls.append((fn, args))


def test_indexing_submits_project_root(db, artifacts_dir, tmp_path):
    # The pipeline must know the project folder — that is where artifacts go.
    root = tmp_path / "Most"
    _make_pdf(root / "tz.pdf")
    sync_archive(db, [root])

    executor = _FakeExecutor()
    submitted, _locked = start_archive_indexing(db, [root], executor)

    assert submitted == 1
    (fn, args) = executor.calls[0]
    assert fn is run_project_pipeline
    assert args == ("most__tz", str(root / "tz.pdf"), str(root))


def test_scan_migrates_local_artifacts_into_folder(db, artifacts_dir, tmp_path):
    # An archive indexed by an old version keeps artifacts in projects_data:
    # the scan moves them into the folder so they are shared from now on.
    root = tmp_path / "Most"
    _make_pdf(root / "tz.pdf")
    slug = make_project_slug("Most", "tz.pdf")
    sync_archive(db, [root])
    doc = db.scalar(select(ProjectDocument).where(ProjectDocument.slug == slug))
    doc.status = "ready"
    db.commit()
    _write_index(artifacts_dir / slug, slug)

    sync_archive(db, [root])

    db.refresh(doc)
    assert doc.status == "ready"
    assert index_store.has_index_files(root, slug)
    assert not (artifacts_dir / slug).exists()  # moved, not copied


def test_migration_failure_keeps_local_artifacts(db, artifacts_dir, tmp_path):
    # .search_index cannot be created (here: the name is taken by a file;
    # in real life: a read-only folder) — artifacts stay local, the
    # document keeps working from the legacy pool.
    root = tmp_path / "Most"
    _make_pdf(root / "tz.pdf")
    slug = make_project_slug("Most", "tz.pdf")
    (root / ".search_index").write_text("not a folder", encoding="utf-8")
    sync_archive(db, [root])
    doc = db.scalar(select(ProjectDocument).where(ProjectDocument.slug == slug))
    doc.status = "ready"
    db.commit()
    _write_index(artifacts_dir / slug, slug)

    sync_archive(db, [root])

    db.refresh(doc)
    assert doc.status == "ready"
    assert (artifacts_dir / slug / "chunks.json").exists()


def test_ready_doc_with_folder_artifacts_stays_ready(db, artifacts_dir, tmp_path):
    # Artifacts only in the folder (already migrated / written by the new
    # pipeline) — no local pool needed.
    root = tmp_path / "Most"
    _make_pdf(root / "tz.pdf")
    slug = make_project_slug("Most", "tz.pdf")
    sync_archive(db, [root])
    doc = db.scalar(select(ProjectDocument).where(ProjectDocument.slug == slug))
    doc.status = "ready"
    db.commit()
    _write_index(index_store.doc_dir(root, slug), slug)

    sync_archive(db, [root])

    db.refresh(doc)
    assert doc.status == "ready"


def test_ready_doc_without_any_artifacts_goes_pending(db, artifacts_dir, tmp_path):
    root = tmp_path / "Most"
    _make_pdf(root / "tz.pdf")
    slug = make_project_slug("Most", "tz.pdf")
    sync_archive(db, [root])
    doc = db.scalar(select(ProjectDocument).where(ProjectDocument.slug == slug))
    doc.status = "ready"
    db.commit()

    sync_archive(db, [root])

    db.refresh(doc)
    assert doc.status == "pending"


def test_replaced_pdf_cleans_folder_artifacts(db, artifacts_dir, tmp_path):
    import os

    root = tmp_path / "Most"
    pdf = root / "tz.pdf"
    _make_pdf(pdf, pages=1)
    slug = make_project_slug("Most", "tz.pdf")
    sync_archive(db, [root])
    doc = db.scalar(select(ProjectDocument).where(ProjectDocument.slug == slug))
    doc.status = "ready"
    db.commit()
    _write_index(index_store.doc_dir(root, slug), slug)

    _make_pdf(pdf, pages=2)
    st = pdf.stat()
    os.utime(pdf, ns=(st.st_atime_ns + 10**10, st.st_mtime_ns + 10**10))
    summary = sync_archive(db, [root])

    db.refresh(doc)
    assert doc.status == "pending"
    assert not index_store.doc_dir(root, slug).exists()
    assert summary.changed == 1


def test_removed_doc_cleans_folder_artifacts(db, artifacts_dir, tmp_path):
    root = tmp_path / "Most"
    pdf = root / "tz.pdf"
    _make_pdf(pdf)
    slug = make_project_slug("Most", "tz.pdf")
    sync_archive(db, [root])
    _write_index(index_store.doc_dir(root, slug), slug)

    pdf.unlink()
    summary = sync_archive(db, [root])

    assert summary.missing == 1
    assert not index_store.doc_dir(root, slug).exists()
    assert db.scalar(select(ProjectDocument)) is None


def test_cache_roots_include_archive_folders(monkeypatch, tmp_path):
    # The search cache must read <archive folder>/.search_index like it
    # reads library folders; the same physical folder attached as both a
    # library and an archive must not be loaded twice.
    from backend.core import database, library_cache

    lib = tmp_path / "lib"
    lib.mkdir()
    proj = tmp_path / "Most"
    proj.mkdir()

    class _DummySession:
        def close(self):
            pass

    monkeypatch.setattr(database, "SessionLocal", lambda: _DummySession())
    monkeypatch.setattr(
        "backend.modules.settings.service.get_library_paths",
        lambda db: [str(lib)],
    )
    monkeypatch.setattr(
        "backend.modules.settings.service.get_projects_paths",
        lambda db: [str(proj), str(lib)],  # lib doubles as archive — dedup
    )

    roots = library_cache._shared_index_roots()

    assert roots == [
        index_store.index_root(lib),
        index_store.index_root(proj),
    ]
