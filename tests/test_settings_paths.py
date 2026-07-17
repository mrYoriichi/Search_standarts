"""Тесты списка папок библиотеки в настройках."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.core.database import Base
from backend.modules.settings import service
from backend.modules.settings.models import Setting  # noqa: F401 — для create_all


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def test_empty_by_default(db):
    assert service.get_library_paths(db) == []


def test_add_and_remove(db, tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()

    service.add_library_path(db, str(a))
    service.add_library_path(db, str(b))
    assert set(service.get_library_paths(db)) == {str(a), str(b)}

    # Повторное добавление той же папки — idempotent.
    service.add_library_path(db, str(a))
    assert len(service.get_library_paths(db)) == 2

    service.remove_library_path(db, str(a))
    assert service.get_library_paths(db) == [str(b)]


def test_add_rejects_missing_dir(db, tmp_path):
    with pytest.raises(ValueError):
        service.add_library_path(db, str(tmp_path / "nope"))


def test_migrates_legacy_single_path(db, tmp_path):
    lib = tmp_path / "Normy"
    lib.mkdir()
    # Старая установка: одна папка в library_path, списка ещё нет.
    service.set_library_path(db, str(lib))
    paths = service.get_library_paths(db)
    assert paths == [str(lib)]
