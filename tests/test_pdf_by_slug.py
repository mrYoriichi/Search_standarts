"""Resolving a document's PDF by slug (clickable sources, strong search).

Audit 2026-08-06 #3: the lookup ignored the path stored at scan time and
re-walked the folder, returning the FIRST file whose name matched the
slug. Two same-named PDFs in different subfolders -> the wrong document
opened, and strong search sent pages of the wrong file to the LLM.
"""

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.core import index_store
from backend.core.database import Base
from backend.modules.documents.models import Document
from backend.modules.library.service import resolve_pdf_by_slug
from backend.modules.settings import service as settings_service


@pytest.fixture
def db():
    """Fresh in-memory SQLite for every test."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _make_library(db, tmp_path, files: list[str]) -> Path:
    """Library folder with meta, the given PDFs, registered in settings."""
    library = tmp_path / "lib"
    library.mkdir()
    for rel in files:
        pdf = library / rel
        pdf.parent.mkdir(parents=True, exist_ok=True)
        pdf.write_bytes(b"%PDF-1.4 fake")
    index_store.ensure_meta(library, "test-model")
    settings_service.add_library_path(db, str(library))
    return library


def _register(db, library: Path, relative_path: str, filename_slug: str) -> str:
    """A ready Document row as the scan would write it. Returns its slug."""
    fid = index_store.read_meta(library)["folder_id"]
    slug = index_store.scoped_slug(fid, filename_slug)
    db.add(
        Document(
            slug=slug,
            title=filename_slug,
            status="ready",
            relative_path=relative_path,
        )
    )
    db.commit()
    return slug


@pytest.mark.parametrize("registered", ["aaa", "zzz"])
def test_pdf_resolved_by_db_path_not_by_first_match(db, tmp_path, registered):
    """Same file name in two subfolders: the indexed one must open.

    Both parameters share one disk layout, so the folder walk returns the
    same file for both — whichever it is, one parameter used to open the
    wrong document.
    """
    library = _make_library(db, tmp_path, ["aaa/norma.pdf", "zzz/norma.pdf"])
    slug = _register(db, library, f"{registered}/norma.pdf", "norma")

    assert resolve_pdf_by_slug(db, slug) == library / registered / "norma.pdf"


def test_pdf_found_when_db_path_is_stale(db, tmp_path):
    """relink does not update relative_path (known issue, self-heals on scan).

    Until the next scan the stored path points at the old file name, so
    the search fallback must still find the renamed PDF.
    """
    library = _make_library(db, tmp_path, ["nove.pdf"])
    slug = _register(db, library, "stare.pdf", "nove")

    assert resolve_pdf_by_slug(db, slug) == library / "nove.pdf"
