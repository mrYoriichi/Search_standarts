"""Tests of the library folder list in settings."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.core.database import Base
from backend.modules.settings import service
from backend.modules.settings.models import Setting  # noqa: F401 — for create_all


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

    # Adding the same folder again is idempotent.
    service.add_library_path(db, str(a))
    assert len(service.get_library_paths(db)) == 2

    service.remove_library_path(db, str(a))
    assert service.get_library_paths(db) == [str(b)]


def test_add_rejects_missing_dir(db, tmp_path):
    with pytest.raises(ValueError):
        service.add_library_path(db, str(tmp_path / "nope"))


def test_update_replaces_in_place(db, tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    c = tmp_path / "c"
    for d in (a, b, c):
        d.mkdir()
    service.add_library_path(db, str(a))
    service.add_library_path(db, str(b))
    # Edit the first folder a -> c, the order is preserved.
    result = service.update_library_path(db, str(a), str(c))
    assert result == [str(c), str(b)]


def test_update_rejects_missing_new_dir(db, tmp_path):
    a = tmp_path / "a"
    a.mkdir()
    service.add_library_path(db, str(a))
    with pytest.raises(ValueError):
        service.update_library_path(db, str(a), str(tmp_path / "nope"))


def test_update_dedups_when_new_already_present(db, tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    service.add_library_path(db, str(a))
    service.add_library_path(db, str(b))
    # Edit a -> b while b already exists: a single b remains.
    result = service.update_library_path(db, str(a), str(b))
    assert result == [str(b)]


def test_migrates_legacy_single_path(db, tmp_path):
    lib = tmp_path / "Normy"
    lib.mkdir()
    # An old install: one folder in library_path, no list yet.
    service.set_library_path(db, str(lib))
    paths = service.get_library_paths(db)
    assert paths == [str(lib)]
