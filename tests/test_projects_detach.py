"""Отключение папки архива: записи её документов уходят из БД.

Живой случай 2026-08-10: папка подключена, не индексирована, путь
удалён — документы висели «čeká» до следующего «Skenovat». Зеркало
библиотечного поведения (test_library_detach), но принадлежность
определяется по имени проекта (= имени папки): слаг архива не несёт
folder_id. Артефакты в `.search_index` не трогаются — повторное
подключение усыновляет их бесплатно.
"""

import shutil
from pathlib import Path

import pypdfium2 as pdfium
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.core.database import Base
from backend.modules.projects.models import ProjectDocument
from backend.modules.projects.service import sync_archive
from backend.modules.settings import service as settings_service


@pytest.fixture
def db():
    """Fresh in-memory SQLite for every test."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _make_project(folder: Path, pdf_name: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    doc = pdfium.PdfDocument.new()
    doc.new_page(200, 100)
    with open(folder / pdf_name, "wb") as f:
        doc.save(f)
    return folder


def _attach_and_scan(db, folder: Path) -> None:
    settings_service.add_projects_path(db, str(folder))
    sync_archive(db, [folder])


def test_detach_removes_project_documents(db, tmp_path):
    project = _make_project(tmp_path / "most_a", "TZ.pdf")
    _attach_and_scan(db, project)
    assert db.scalar(select(ProjectDocument)) is not None

    settings_service.remove_projects_path(db, str(project))

    assert db.scalars(select(ProjectDocument)).all() == []


def test_detach_keeps_other_folders_documents(db, tmp_path):
    first = _make_project(tmp_path / "most_a", "Jedna.pdf")
    second = _make_project(tmp_path / "most_b", "Dva.pdf")
    _attach_and_scan(db, first)
    _attach_and_scan(db, second)

    settings_service.remove_projects_path(db, str(first))

    docs = db.scalars(select(ProjectDocument)).all()
    assert [doc.project for doc in docs] == ["most_b"]


def test_detach_namesake_folder_keeps_documents(db, tmp_path):
    """Среди оставшихся папок тёзка (то же имя проекта) — не удаляем:
    лучше сироты, чем снести документы чужой папки."""
    kept = _make_project(tmp_path / "x" / "most", "TZ.pdf")
    _attach_and_scan(db, kept)
    namesake = tmp_path / "y" / "most"
    namesake.mkdir(parents=True)
    settings_service.add_projects_path(db, str(namesake))

    settings_service.remove_projects_path(db, str(tmp_path / "y" / "most"))

    assert len(db.scalars(select(ProjectDocument)).all()) == 1


def test_detach_unavailable_folder_removes_documents(db, tmp_path):
    """Папка уже недоступна (диск отвалился): отключение — осознанное
    действие юзера, записи удаляем по имени, папку не читаем."""
    project = _make_project(tmp_path / "most_a", "TZ.pdf")
    _attach_and_scan(db, project)
    shutil.rmtree(project)

    settings_service.remove_projects_path(db, str(project))

    assert db.scalars(select(ProjectDocument)).all() == []


def test_detach_skips_processing_document(db, tmp_path):
    """processing не удаляем: пайплайн ещё пишет статус по этой записи."""
    project = _make_project(tmp_path / "most_a", "TZ.pdf")
    _attach_and_scan(db, project)
    doc = db.scalar(select(ProjectDocument))
    doc.status = "processing"
    db.commit()

    settings_service.remove_projects_path(db, str(project))

    assert db.scalar(select(ProjectDocument)).status == "processing"
