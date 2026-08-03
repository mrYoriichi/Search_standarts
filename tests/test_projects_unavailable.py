"""Tests for audit bug #2: an unavailable archive folder (network drive
went offline) must not be treated as empty — otherwise "Skenovat" deletes
DB rows and indexes, and after the drive comes back the documents get
re-indexed again for money.

Archive documents carry no folder tag (slug = {project}__{file}), so with
ANY unavailable folder the deletion of "missing" ones is skipped entirely —
there is no way to tell whose they are. The library got the same guard in
commit 3e20d55.
"""

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.core.database import Base
from backend.modules.projects import service
from backend.modules.projects.models import ProjectDocument
from backend.modules.projects.service import sync_archive


@pytest.fixture
def db():
    """Fresh in-memory SQLite for each test."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture
def artifacts_dir(tmp_path, monkeypatch):
    """Archive artifacts pool — in a temp folder, not in data/."""
    pool = tmp_path / "projects_data"
    pool.mkdir()
    monkeypatch.setattr(service, "PROJECTS_DATA_DIR", pool)
    return pool


def _add_ready_doc(db, artifacts_dir, slug: str = "alfa_most__tz") -> str:
    """Ready archive document: a DB row + an artifacts folder on disk."""
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
    dead = tmp_path / "unplugged_disk"  # folder does not exist

    summary = sync_archive(db, [dead])

    doc = db.scalar(select(ProjectDocument).where(ProjectDocument.slug == slug))
    assert doc is not None
    assert (artifacts_dir / slug).exists()
    assert summary.missing == 0
    assert summary.unavailable == [str(dead)]


def test_mixed_roots_skip_deletion(db, artifacts_dir, tmp_path):
    # One folder is alive (empty), the other went offline → skip deletion
    # entirely: without a folder tag we can't tell whose the missing doc is.
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
    # All folders available, the file is gone → old behavior: clean the DB
    # and indexes (removing a file from the folder is a deliberate user act).
    slug = _add_ready_doc(db, artifacts_dir)
    alive = tmp_path / "alive"
    alive.mkdir()

    summary = sync_archive(db, [alive])

    doc = db.scalar(select(ProjectDocument).where(ProjectDocument.slug == slug))
    assert doc is None
    assert not (artifacts_dir / slug).exists()
    assert summary.missing == 1
    assert summary.unavailable == []
