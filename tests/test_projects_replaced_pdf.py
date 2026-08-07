"""A replaced archive PDF (same path, new content) must get reindexed.

The scan used to compare only the slug: a file with new content stayed ready
with the old chunks — search silently served stale data until the user
pressed 🔄 manually (and only on their own machine).
"""

import os
from pathlib import Path

import pypdfium2 as pdfium
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.core.database import Base
from backend.modules.projects import service
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
    monkeypatch.setattr(service, "PROJECTS_DATA_DIR", pool)
    return pool


def _make_pdf(path: Path, pages: int = 1) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = pdfium.PdfDocument.new()
    for _ in range(pages):
        doc.new_page(595, 842)
    doc.save(path)
    doc.close()


def _bump_mtime(path: Path, seconds: int = 10) -> None:
    """An explicit mtime shift: coarse file systems change it once per 1-2 s."""
    st = path.stat()
    ns = seconds * 1_000_000_000
    os.utime(path, ns=(st.st_atime_ns + ns, st.st_mtime_ns + ns))


def _scan_ready(db, artifacts_dir, root: Path, slug: str):
    """First scan + moving the document to ready with artifacts on disk."""
    sync_archive(db, [root])
    doc = db.scalar(select(ProjectDocument).where(ProjectDocument.slug == slug))
    doc.status = "ready"
    db.commit()
    (artifacts_dir / slug).mkdir()
    (artifacts_dir / slug / "chunks.json").write_text("[]", encoding="utf-8")
    return doc


def test_replaced_pdf_resets_to_pending(db, artifacts_dir, tmp_path):
    root = tmp_path / "Most"
    pdf = root / "tz.pdf"
    _make_pdf(pdf, pages=1)
    slug = make_project_slug("Most", "tz.pdf")
    doc = _scan_ready(db, artifacts_dir, root, slug)

    _make_pdf(pdf, pages=2)  # replacement: different content and size
    _bump_mtime(pdf)
    summary = sync_archive(db, [root])

    db.refresh(doc)
    assert doc.status == "pending"
    assert doc.error is None
    assert doc.page_count == 2
    assert not (artifacts_dir / slug).exists()  # old chunks cleaned up
    assert summary.changed == 1


def test_unchanged_pdf_stays_ready(db, artifacts_dir, tmp_path):
    root = tmp_path / "Most"
    _make_pdf(root / "tz.pdf", pages=1)
    slug = make_project_slug("Most", "tz.pdf")
    doc = _scan_ready(db, artifacts_dir, root, slug)

    summary = sync_archive(db, [root])

    db.refresh(doc)
    assert doc.status == "ready"
    assert (artifacts_dir / slug).exists()
    assert summary.changed == 0


def test_legacy_row_backfills_without_reset(db, artifacts_dir, tmp_path):
    # Rows from an old app version (no stat columns) must NOT be mass-reset
    # to pending — that means paying vision again for the whole archive.
    root = tmp_path / "Most"
    _make_pdf(root / "tz.pdf", pages=1)
    slug = make_project_slug("Most", "tz.pdf")
    db.add(
        ProjectDocument(
            slug=slug,
            project="Most",
            relative_path="tz.pdf",
            doc_type="text",
            page_count=1,
            status="ready",
        )
    )
    db.commit()
    (artifacts_dir / slug).mkdir()

    summary = sync_archive(db, [root])

    doc = db.scalar(select(ProjectDocument).where(ProjectDocument.slug == slug))
    assert doc.status == "ready"
    assert (artifacts_dir / slug).exists()
    assert doc.file_size is not None  # stat filled in for the next scans
    assert summary.changed == 0


def test_processing_doc_not_reset(db, artifacts_dir, tmp_path):
    # The file was replaced WHILE the pipeline runs: don't pull the rug,
    # don't update the stat — the next scan after processing catches the swap.
    root = tmp_path / "Most"
    pdf = root / "tz.pdf"
    _make_pdf(pdf, pages=1)
    slug = make_project_slug("Most", "tz.pdf")
    sync_archive(db, [root])
    doc = db.scalar(select(ProjectDocument).where(ProjectDocument.slug == slug))
    old_mtime = doc.file_mtime
    doc.status = "processing"
    db.commit()

    _make_pdf(pdf, pages=2)
    _bump_mtime(pdf)
    summary = sync_archive(db, [root])

    db.refresh(doc)
    assert doc.status == "processing"
    assert doc.file_mtime == old_mtime
    assert summary.changed == 0


class _FakeExecutor:
    def __init__(self):
        self.calls = []

    def submit(self, fn, *args, **kwargs):
        self.calls.append((fn, args))


def test_index_archive_refreshes_stat(db, artifacts_dir, tmp_path):
    # The file was replaced between "Skenovat" and "Indexovat": the pipeline
    # will read the NEW version from disk — the stat in the DB must match it,
    # or the next scan deems the freshly paid index stale and resets it.
    from backend.modules.projects.service import start_archive_indexing

    root = tmp_path / "Most"
    pdf = root / "tz.pdf"
    _make_pdf(pdf, pages=1)
    slug = make_project_slug("Most", "tz.pdf")
    sync_archive(db, [root])

    _make_pdf(pdf, pages=2)
    _bump_mtime(pdf)

    executor = _FakeExecutor()
    submitted, locked = start_archive_indexing(db, [root], executor)

    doc = db.scalar(select(ProjectDocument).where(ProjectDocument.slug == slug))
    assert submitted == 1
    assert locked == []
    assert len(executor.calls) == 1
    assert doc.status == "processing"
    assert doc.file_size == pdf.stat().st_size
    assert doc.file_mtime == pytest.approx(pdf.stat().st_mtime)
