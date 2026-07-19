"""Тесты бага №2 аудита: недоступная папка архива (отвалился сетевой диск)
не должна считаться пустой — иначе «Skenovat» удаляет записи БД и индексы,
и после возврата диска документы индексируются заново за деньги.

Документы архива не несут метку папки (slug = {проект}__{файл}), поэтому
при ЛЮБОЙ недоступной папке удаление «пропавших» пропускается целиком —
не понять, чьи они. Библиотека получила такой же гард в коммите 3e20d55.
"""

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.core import paths
from backend.core.database import Base
from backend.modules.projects.models import ProjectDocument
from backend.modules.projects.service import sync_archive


@pytest.fixture
def db():
    """Чистая in-memory SQLite на каждый тест."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture
def artifacts_dir(tmp_path, monkeypatch):
    """Пул артефактов архива — во временной папке, не в data/."""
    pool = tmp_path / "projects_data"
    pool.mkdir()
    monkeypatch.setattr(paths, "PROJECTS_DATA_DIR", pool)
    return pool


def _add_ready_doc(db, artifacts_dir, slug: str = "alfa_most__tz") -> str:
    """Готовый документ архива: строка в БД + папка артефактов на диске."""
    db.add(
        ProjectDocument(
            slug=slug,
            project="Alfa_most",
            relative_path="Alfa_most/tz.pdf",
            doc_type="text",
            page_count=1,
            status="ready",
        )
    )
    db.commit()
    (artifacts_dir / slug).mkdir()
    (artifacts_dir / slug / "chunks.json").write_text("[]", encoding="utf-8")
    return slug


def test_unavailable_root_keeps_documents(db, artifacts_dir, tmp_path):
    slug = _add_ready_doc(db, artifacts_dir)
    dead = tmp_path / "unplugged_disk"  # папка не существует

    summary = sync_archive(db, [dead])

    doc = db.scalar(select(ProjectDocument).where(ProjectDocument.slug == slug))
    assert doc is not None
    assert (artifacts_dir / slug).exists()
    assert summary.missing == 0
    assert summary.unavailable == [str(dead)]


def test_mixed_roots_skip_deletion(db, artifacts_dir, tmp_path):
    # Одна папка жива (пустая), другая отвалилась → удаление пропускаем
    # целиком: без метки папки не понять, чей пропавший документ.
    slug = _add_ready_doc(db, artifacts_dir)
    alive = tmp_path / "alive"
    alive.mkdir()
    dead = tmp_path / "dead"

    summary = sync_archive(db, [alive, dead])

    doc = db.scalar(select(ProjectDocument).where(ProjectDocument.slug == slug))
    assert doc is not None
    assert (artifacts_dir / slug).exists()
    assert summary.missing == 0
    assert summary.unavailable == [str(dead)]


def test_missing_file_in_available_root_still_removed(db, artifacts_dir, tmp_path):
    # Все папки доступны, файла нет → прежнее поведение: чистим БД и индексы
    # (удаление файла из папки — осознанное действие юзера).
    slug = _add_ready_doc(db, artifacts_dir)
    alive = tmp_path / "alive"
    alive.mkdir()

    summary = sync_archive(db, [alive])

    doc = db.scalar(select(ProjectDocument).where(ProjectDocument.slug == slug))
    assert doc is None
    assert not (artifacts_dir / slug).exists()
    assert summary.missing == 1
    assert summary.unavailable == []
