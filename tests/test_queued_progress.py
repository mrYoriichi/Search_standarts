"""«čeká ve frontě» отдельно от «zpracovává se» (решение 2026-08-09).

Шлюз parse пускает в CPU-тяжёлую стадию один документ, но статус
processing получают сразу все отправленные — до трёх документов
выглядели «zpracovává se», хотя реально ждали очереди часами. Теперь
при отправке в executor ставится прогресс «čeká ve frontě…»; первый
настоящий этап («čtení PDF…») перекрывает его только после входа в
шлюз — до того юзер честно видит очередь.
"""

from pathlib import Path

import pypdfium2 as pdfium
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.core import progress
from backend.core.database import Base
from backend.core.ui_messages import msg
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
    """Записывает задания, не выполняя их: документ «встал в очередь»."""

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


def test_library_start_marks_documents_queued(db, tmp_path):
    library = _make_pdf(tmp_path / "normy", "Norma.pdf")
    scan_library([library], db)
    executor = _FakeExecutor()

    submitted, _locked = start_indexing([library], db, executor)

    assert submitted == 1
    slug = db.scalar(select(Document)).slug
    assert progress.get_progress(slug) == msg("progress.queued")
    progress.clear_progress(slug)


def test_archive_start_marks_documents_queued(db, tmp_path):
    root = _make_pdf(tmp_path / "most_a", "TZ.pdf")
    sync_archive(db, [root])
    executor = _FakeExecutor()

    submitted, _locked = start_archive_indexing(db, [root], executor)

    assert submitted == 1
    slug = db.scalar(select(ProjectDocument)).slug
    assert progress.get_progress(slug) == msg("progress.queued")
    progress.clear_progress(slug)
