"""Выборочный запуск: «Indexovat» для одного документа (решение
2026-08-11). Кнопка ▶ у pending-файла шлёт в пайплайн только его —
остальные остаются «čeká» и денег не тратят.
"""

from pathlib import Path

import pypdfium2 as pdfium
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.core.database import Base
from backend.modules.documents.models import Document
from backend.modules.library.service import scan_library, start_indexing
from backend.modules.projects.models import ProjectDocument
from backend.modules.projects.service import start_archive_indexing, sync_archive


@pytest.fixture
def db():
    """Fresh in-memory SQLite for every test."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


class _FakeExecutor:
    def __init__(self):
        self.calls = []

    def submit(self, fn, *args):
        self.calls.append((fn, args))


def _make_pdf(folder: Path, pdf_name: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    doc = pdfium.PdfDocument.new()
    doc.new_page(200, 100)
    with open(folder / pdf_name, "wb") as f:
        doc.save(f)
    return folder


def test_library_index_single_document(db, tmp_path):
    library = _make_pdf(tmp_path / "normy", "Jedna.pdf")
    _make_pdf(library, "Dva.pdf")
    scan_library([library], db)
    docs = {d.relative_path: d for d in db.scalars(select(Document)).all()}
    target = docs["Jedna.pdf"]
    executor = _FakeExecutor()

    started, _locked = start_indexing([library], db, executor, only_slug=target.slug)

    assert started == 1
    assert len(executor.calls) == 1
    assert target.status == "processing"
    assert docs["Dva.pdf"].status == "pending"  # второй не тронут


def test_archive_index_single_document(db, tmp_path):
    root = _make_pdf(tmp_path / "most_a", "TZ.pdf")
    _make_pdf(root, "VV.pdf")
    sync_archive(db, [root])
    docs = {d.relative_path: d for d in db.scalars(select(ProjectDocument)).all()}
    target = docs["TZ.pdf"]
    executor = _FakeExecutor()

    started, _locked = start_archive_indexing(
        db, [root], executor, only_slug=target.slug
    )

    assert started == 1
    assert len(executor.calls) == 1
    assert target.status == "processing"
    assert docs["VV.pdf"].status == "pending"  # второй не тронут


def test_index_single_unknown_slug_is_noop(db, tmp_path):
    # Кнопка могла «прокиснуть» в UI (документ уже удалён/запущен) —
    # запуск по несуществующему slug ничего не делает и не падает.
    library = _make_pdf(tmp_path / "normy", "Jedna.pdf")
    scan_library([library], db)
    executor = _FakeExecutor()

    started, _locked = start_indexing([library], db, executor, only_slug="ghost")

    assert started == 0
    assert executor.calls == []
