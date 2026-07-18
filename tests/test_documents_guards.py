"""Тесты защиты операций над документом во время индексации.

Удаление/переиндексация/relink работающего документа раньше давали гонку:
фоновый pipeline дописывал артефакты уже после rmtree, и следующий скан
«усыновлял» удалённый документ обратно (двойная оплата vision).
"""

import io

import pytest
from fastapi import UploadFile
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.core.database import Base
from backend.modules.documents import service
from backend.modules.documents.models import Document


@pytest.fixture
def db():
    """Чистая in-memory SQLite на каждый тест."""
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
    # Документ остался в БД — ничего не удалено.
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


class _FakeExecutor:
    def __init__(self):
        self.calls = []

    def submit(self, fn, *args):
        self.calls.append((fn, args))


def test_upload_passes_pdf_path_to_pipeline(db, tmp_path, monkeypatch):
    # Без pdf_path describe молча пропускал vision-паспорта чертёжных страниц.
    monkeypatch.setattr(service, "PDF_STORAGE_DIR", tmp_path / "pdfs")
    executor = _FakeExecutor()
    upload = UploadFile(file=io.BytesIO(b"%PDF-1.4 fake"), filename="Vykres.pdf")

    items = service.create_documents_from_uploads([upload], db, executor)

    assert items[0].action == "created"
    (fn, args) = executor.calls[0]
    assert fn is service.run_pipeline
    slug, pdf_path = args
    assert slug == "vykres"
    assert pdf_path.endswith("vykres.pdf")
