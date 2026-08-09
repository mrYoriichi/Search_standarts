"""A PDF that is on disk but cannot be opened must not vanish on scan.

The scan used to treat "file exists but does not open" (broken PDF, file
locked by another program) the same as "file deleted": the row and the
paid artifacts were wiped. Now such a file stays in the list with the
error status — deletion is only for files really gone from disk.
"""

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


def _make_pdf(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = pdfium.PdfDocument.new()
    doc.new_page(595, 842)
    doc.save(path)
    doc.close()


def test_broken_pdf_shows_as_error_not_deleted(db, artifacts_dir, tmp_path):
    root = tmp_path / "Most"
    root.mkdir()
    (root / "bad.pdf").write_bytes(b"not a pdf at all")

    summary = sync_archive(db, [root])

    doc = db.scalar(select(ProjectDocument))
    assert doc is not None
    assert doc.status == "error"
    assert doc.error
    assert summary.errors  # the scan summary still reports the file

    # Rescan: the row survives, no duplicates appear.
    sync_archive(db, [root])
    docs = db.scalars(select(ProjectDocument)).all()
    assert len(docs) == 1
    assert docs[0].status == "error"


def test_failed_doc_survives_scan_when_file_unreadable(db, artifacts_dir, tmp_path):
    # Домашний сценарий: документ упал в пайплайне (точная причина в
    # error), после перезапуска юзер жмёт «Skenovat», файл не читается —
    # раньше строка молча удалялась вместе с причиной ошибки.
    root = tmp_path / "Most"
    pdf = root / "tz.pdf"
    _make_pdf(pdf)
    slug = make_project_slug("Most", "tz.pdf")
    sync_archive(db, [root])
    doc = db.scalar(select(ProjectDocument).where(ProjectDocument.slug == slug))
    doc.status = "error"
    doc.error = "os error 1455"
    db.commit()

    pdf.write_bytes(b"broken now")  # файл стал нечитаемым
    sync_archive(db, [root])

    docs = db.scalars(select(ProjectDocument)).all()
    assert len(docs) == 1
    assert docs[0].status == "error"
    assert docs[0].error == "os error 1455"  # точная причина не затёрта
