"""Отключение папки библиотеки: записи её документов уходят из БД.

Индекс в `.search_index` внутри папки не трогается — при повторном
подключении скан усыновляет его бесплатно (см. test_library_scan).
"""

import shutil

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.core.database import Base
from backend.modules.documents.models import Document
from backend.modules.library.service import scan_library
from backend.modules.settings import service as settings_service


@pytest.fixture
def db():
    """Fresh in-memory SQLite for every test."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _make_library(folder, pdf_name: str):
    """Library folder with one PDF (scan never opens it; only the name matters)."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / pdf_name).write_bytes(b"%PDF-1.4 fake")
    return folder


def _attach_and_scan(db, folder) -> None:
    settings_service.add_library_path(db, str(folder))
    scan_library([folder], db)


def test_detach_removes_folder_documents(db, tmp_path):
    library = _make_library(tmp_path / "normy", "Norma.pdf")
    _attach_and_scan(db, library)
    assert db.scalar(select(Document)) is not None

    settings_service.remove_library_path(db, str(library))

    assert db.scalars(select(Document)).all() == []
    # Индекс на диске остался — повторное подключение усыновит его.
    assert (library / ".search_index").exists()


def test_detach_keeps_other_folders_documents(db, tmp_path):
    first = _make_library(tmp_path / "a", "Jedna.pdf")
    second = _make_library(tmp_path / "b", "Dva.pdf")
    _attach_and_scan(db, first)
    _attach_and_scan(db, second)

    settings_service.remove_library_path(db, str(first))

    slugs = [doc.slug for doc in db.scalars(select(Document)).all()]
    assert len(slugs) == 1
    assert "dva" in slugs[0]


def test_detach_unavailable_folder_keeps_documents(db, tmp_path):
    """Папка пропала (сетевой диск): ярлык не прочитать — записи не трогаем."""
    library = _make_library(tmp_path / "sit", "Norma.pdf")
    _attach_and_scan(db, library)
    shutil.rmtree(library)

    settings_service.remove_library_path(db, str(library))

    assert len(db.scalars(select(Document)).all()) == 1


def test_detach_skips_processing_document(db, tmp_path):
    """processing не удаляем: пайплайн ещё пишет статус по этой записи."""
    library = _make_library(tmp_path / "normy", "Norma.pdf")
    _attach_and_scan(db, library)
    doc = db.scalar(select(Document))
    doc.status = "processing"
    db.commit()

    settings_service.remove_library_path(db, str(library))

    assert db.scalar(select(Document)).status == "processing"
