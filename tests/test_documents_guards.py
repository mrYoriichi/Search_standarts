"""Тесты защиты операций над документом во время индексации.

Удаление/переиндексация/relink работающего документа раньше давали гонку:
фоновый pipeline дописывал артефакты уже после rmtree, и следующий скан
«усыновлял» удалённый документ обратно (двойная оплата vision).
"""

import io
import json
import time

import pytest
from fastapi import UploadFile
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.core import index_lock, index_store
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


def _make_locked_library(tmp_path, filename_slug: str, lock_age: float = 0.0):
    """Папка библиотеки с meta, артефактами документа и ЧУЖИМ локом.

    Возвращает (папка, scoped-slug документа). lock_age — возраст лока в
    секундах (0 = свежий, индексация другой машины идёт прямо сейчас).
    """
    library = tmp_path / "lib"
    library.mkdir()
    index_store.ensure_meta(library, "test-model")
    fid = index_store.read_meta(library)["folder_id"]
    slug = index_store.scoped_slug(fid, filename_slug)
    artifacts = index_store.doc_dir(library, slug)
    artifacts.mkdir(parents=True)
    (artifacts / "chunks.json").write_text("[]", encoding="utf-8")
    lock_path = index_store.index_root(library) / index_lock.LOCK_FILENAME
    lock_path.write_text(
        json.dumps({"owner": "PC-KOLEGA", "ts": time.time() - lock_age}),
        encoding="utf-8",
    )
    return library, slug


def test_delete_refused_when_foreign_lock(db, tmp_path):
    # №4 из аудита: чужая машина индексирует папку — rmtree у неё из-под ног
    # уронил бы её пайплайн (оплаченный vision пропал бы).
    library, slug = _make_locked_library(tmp_path, "norma")
    _add_doc(db, slug, "ready")

    with pytest.raises(service.DocumentBusyError):
        service.delete_document(db, slug, paths=[library])

    assert db.scalar(select(Document).where(Document.slug == slug)) is not None
    assert index_store.doc_dir(library, slug).exists()


def test_relink_refused_when_foreign_lock(db, tmp_path):
    library, old_slug = _make_locked_library(tmp_path, "stare")
    _add_doc(db, old_slug, "ready")
    fid = index_store.folder_id_of(old_slug)
    new_slug = index_store.scoped_slug(fid, "nove")

    with pytest.raises(service.DocumentBusyError):
        service.relink_document(db, old_slug, new_slug, paths=[library])

    # Ничего не переименовано, slug в БД прежний.
    assert index_store.doc_dir(library, old_slug).exists()
    assert db.scalar(select(Document).where(Document.slug == old_slug)) is not None


def test_delete_works_when_lock_stale(db, tmp_path):
    # Протухший лок (машина упала) — не повод блокировать удаление.
    library, slug = _make_locked_library(
        tmp_path, "norma", lock_age=index_lock.TTL_SECONDS + 1
    )
    _add_doc(db, slug, "ready")

    service.delete_document(db, slug, paths=[library])

    assert db.scalar(select(Document).where(Document.slug == slug)) is None
    assert not index_store.doc_dir(library, slug).exists()


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
