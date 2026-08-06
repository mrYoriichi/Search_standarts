"""A ready document whose artifacts are gone must return to pending.

Audit 2026-08-06 #5: delete/reindex/relink remove files first and write the
DB after. A crash in between leaves a document showing "hotovo" with
nothing to search, and no rescan ever revalidated ready rows — it stayed
silently missing from answers until the user pressed reindex by hand.

The check is deliberately cheap (existence only, no JSON parsing): scans
walk network folders, and a full parse of every embeddings.json would cost
seconds per document.
"""

import shutil
from pathlib import Path

import pypdfium2 as pdfium
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.core import index_store
from backend.core.database import Base
from backend.modules.documents.models import Document
from backend.modules.library.service import scan_library
from backend.modules.projects import service as projects_service
from backend.modules.projects.models import ProjectDocument
from backend.modules.projects.service import make_project_slug, sync_archive


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
    monkeypatch.setattr(projects_service, "PROJECTS_DATA_DIR", pool)
    return pool


def _make_ready_library(tmp_path, with_artifacts: bool) -> tuple[Path, str]:
    """A library folder with one ready PDF, artifacts optional."""
    library = tmp_path / "lib"
    library.mkdir()
    (library / "norma.pdf").write_bytes(b"%PDF-1.4 fake")
    index_store.ensure_meta(library, "test-model")
    fid = index_store.read_meta(library)["folder_id"]
    slug = index_store.scoped_slug(fid, "norma")
    if with_artifacts:
        d = index_store.doc_dir(library, slug)
        d.mkdir(parents=True)
        (d / "chunks.json").write_text("[]", encoding="utf-8")
        (d / "embeddings.json").write_text("{}", encoding="utf-8")
    return library, slug


def _add_ready_doc(db, slug: str) -> Document:
    doc = Document(slug=slug, title="norma", status="ready", relative_path="norma.pdf")
    db.add(doc)
    db.commit()
    return doc


def test_library_ready_without_artifacts_returns_to_pending(db, tmp_path):
    library, slug = _make_ready_library(tmp_path, with_artifacts=False)
    _add_ready_doc(db, slug)

    scan_library([library], db)

    doc = db.scalar(select(Document).where(Document.slug == slug))
    assert doc.status == "pending"


def test_library_ready_with_artifacts_stays_ready(db, tmp_path):
    library, slug = _make_ready_library(tmp_path, with_artifacts=True)
    _add_ready_doc(db, slug)

    scan_library([library], db)

    doc = db.scalar(select(Document).where(Document.slug == slug))
    assert doc.status == "ready"


def test_library_pending_is_left_alone(db, tmp_path):
    """Only ready rows are revalidated: pending has no artifacts by design."""
    library, slug = _make_ready_library(tmp_path, with_artifacts=False)
    doc = _add_ready_doc(db, slug)
    doc.status = "pending"
    db.commit()

    scan_library([library], db)

    db.refresh(doc)
    assert doc.status == "pending"


def _make_pdf(path: Path, pages: int = 1) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = pdfium.PdfDocument.new()
    for _ in range(pages):
        doc.new_page(595, 842)
    doc.save(path)
    doc.close()


def _archive_ready(db, artifacts_dir, root: Path, slug: str) -> ProjectDocument:
    """First scan, then the document goes ready with artifacts on disk."""
    sync_archive(db, [root])
    doc = db.scalar(select(ProjectDocument).where(ProjectDocument.slug == slug))
    doc.status = "ready"
    db.commit()
    (artifacts_dir / slug).mkdir()
    (artifacts_dir / slug / "chunks.json").write_text("[]", encoding="utf-8")
    return doc


def test_archive_ready_without_artifacts_returns_to_pending(
    db, artifacts_dir, tmp_path
):
    root = tmp_path / "Most"
    _make_pdf(root / "tz.pdf")
    slug = make_project_slug("Most", "tz.pdf")
    doc = _archive_ready(db, artifacts_dir, root, slug)
    shutil.rmtree(artifacts_dir / slug)  # crash after rmtree, before the commit

    sync_archive(db, [root])

    db.refresh(doc)
    assert doc.status == "pending"
    assert doc.error is None


def test_archive_processing_without_artifacts_is_left_alone(
    db, artifacts_dir, tmp_path
):
    """The pipeline writes artifacts at the end — processing has none yet."""
    root = tmp_path / "Most"
    _make_pdf(root / "tz.pdf")
    slug = make_project_slug("Most", "tz.pdf")
    sync_archive(db, [root])
    doc = db.scalar(select(ProjectDocument).where(ProjectDocument.slug == slug))
    doc.status = "processing"
    db.commit()

    sync_archive(db, [root])

    db.refresh(doc)
    assert doc.status == "processing"
