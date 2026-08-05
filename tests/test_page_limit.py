"""Page limit of the public build (decision 2026-08-02, 5000 pages).

The search cache loads ALL ready indexes fully into RAM, so the limit must
cut both ways documents can appear: paid indexing AND free adoption —
otherwise a big shared folder kills the app by memory before the pipeline
ever runs. The pilot build has no limit.
"""

import json

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.core import index_store, limits
from backend.core.database import Base
from backend.modules.documents.models import Document
from backend.modules.library import service as library_service
from backend.modules.projects import service as projects_service
from backend.modules.projects.models import ProjectDocument


@pytest.fixture
def db():
    """Fresh in-memory SQLite for each test."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


class _FakeExecutor:
    def __init__(self):
        self.calls = []

    def submit(self, fn, *args):
        self.calls.append((fn, args))


def _lib_doc(db, slug: str, status: str, pages: int | None) -> Document:
    doc = Document(
        slug=slug,
        title=slug,
        status=status,
        page_count=pages,
        relative_path=f"{slug}.pdf",
    )
    db.add(doc)
    db.commit()
    return doc


def _arc_doc(
    db,
    slug: str,
    status: str,
    pages: int,
    project: str = "Alfa_most",
    rel: str = "tz.pdf",
) -> ProjectDocument:
    doc = ProjectDocument(
        slug=slug,
        project=project,
        relative_path=rel,
        doc_type="text",
        page_count=pages,
        status=status,
    )
    db.add(doc)
    db.commit()
    return doc


def _make_indexed_library(tmp_path, pdf_name: str):
    """Library folder with a PDF and a READY index (adoption candidate)."""
    from indexing.embeddings_index import EMBEDDING_MODEL

    library = tmp_path / "lib"
    library.mkdir(parents=True, exist_ok=True)
    (library / pdf_name).write_bytes(b"%PDF-1.4 fake")
    index_store.ensure_meta(library, EMBEDDING_MODEL)
    fid = index_store.read_meta(library)["folder_id"]
    slug = index_store.scoped_slug(fid, pdf_name[:-4].lower())
    d = index_store.doc_dir(library, slug)
    d.mkdir(parents=True)
    (d / "chunks.json").write_text(
        json.dumps([{"chunk_id": f"{slug}_c001", "text": "obsah"}]), encoding="utf-8"
    )
    (d / "embeddings.json").write_text(
        json.dumps(
            {
                "model": EMBEDDING_MODEL,
                "items": [{"chunk_id": f"{slug}_c001", "embedding": [0.1]}],
            }
        ),
        encoding="utf-8",
    )
    return library, slug


# --- Counting pages in use ---------------------------------------------------


def test_pages_in_use_counts_ready_and_processing_in_both_pools(db):
    _lib_doc(db, "a", "ready", 100)
    _lib_doc(db, "b", "processing", 50)  # already in progress — takes memory
    _lib_doc(db, "c", "pending", 999)  # not occupying yet
    _lib_doc(db, "d", "ready", None)  # legacy row without a counter
    _arc_doc(db, "p__tz", "ready", 30)
    assert limits.pages_in_use(db) == 180


def test_pages_remaining_disabled_in_pilot_build(db, monkeypatch):
    monkeypatch.setattr(limits, "PUBLIC_BUILD", False)
    assert limits.pages_remaining(db) is None


def test_pages_remaining_never_negative(db, monkeypatch):
    monkeypatch.setattr(limits, "PUBLIC_BUILD", True)
    monkeypatch.setattr(limits, "PAGE_LIMIT", 10)
    _lib_doc(db, "a", "ready", 100)
    assert limits.pages_remaining(db) == 0


# --- Adoption during scan ----------------------------------------------------


def test_scan_does_not_adopt_beyond_limit(db, tmp_path, monkeypatch):
    monkeypatch.setattr(limits, "PUBLIC_BUILD", True)
    monkeypatch.setattr(limits, "PAGE_LIMIT", 3)
    monkeypatch.setattr(library_service, "count_pages", lambda p: 5)
    library, slug = _make_indexed_library(tmp_path, "Norma.pdf")

    summary = library_service.scan_library([library], db)

    doc = db.scalar(select(Document).where(Document.slug == slug))
    assert doc.status == "pending"  # visible in the list, but NOT ready
    assert summary.adopted == 0
    assert summary.limit_skipped == 1


def test_scan_adopts_under_limit_and_stores_pages(db, tmp_path, monkeypatch):
    monkeypatch.setattr(limits, "PUBLIC_BUILD", True)
    monkeypatch.setattr(limits, "PAGE_LIMIT", 10)
    monkeypatch.setattr(library_service, "count_pages", lambda p: 5)
    library, slug = _make_indexed_library(tmp_path, "Norma.pdf")

    summary = library_service.scan_library([library], db)

    doc = db.scalar(select(Document).where(Document.slug == slug))
    assert doc.status == "ready"
    assert doc.page_count == 5
    assert summary.adopted == 1
    assert summary.limit_skipped == 0


# --- Library indexing --------------------------------------------------------


def test_start_indexing_stops_at_limit(db, tmp_path, monkeypatch):
    from indexing.embeddings_index import EMBEDDING_MODEL

    monkeypatch.setattr(limits, "PUBLIC_BUILD", True)
    monkeypatch.setattr(limits, "PAGE_LIMIT", 12)
    library = tmp_path / "lib"
    library.mkdir()
    index_store.ensure_meta(library, EMBEDDING_MODEL)
    fid = index_store.read_meta(library)["folder_id"]
    for name, pages in [("A.pdf", 5), ("B.pdf", 10)]:
        (library / name).write_bytes(b"%PDF-1.4 fake")
        db.add(
            Document(
                slug=index_store.scoped_slug(fid, name[:-4].lower()),
                title=name,
                status="pending",
                relative_path=name,
                page_count=pages,
            )
        )
    db.commit()

    executor = _FakeExecutor()
    started, locked, over_limit = library_service.start_indexing(
        [library], db, executor
    )

    assert (started, locked, over_limit) == (1, [], 1)
    statuses = {d.slug.split("__")[1]: d.status for d in db.scalars(select(Document))}
    assert statuses == {"a": "processing", "b": "pending"}
    assert len(executor.calls) == 1


# --- Archive indexing --------------------------------------------------------


def test_archive_indexing_stops_at_limit(db, tmp_path, monkeypatch):
    monkeypatch.setattr(limits, "PUBLIC_BUILD", True)
    monkeypatch.setattr(limits, "PAGE_LIMIT", 6)
    root = tmp_path / "Alfa_most"
    root.mkdir()
    (root / "tz.pdf").write_bytes(b"%PDF-1.4 fake")
    (root / "statika.pdf").write_bytes(b"%PDF-1.4 fake")
    _arc_doc(db, "alfa_most__tz", "pending", 4, rel="tz.pdf")
    _arc_doc(db, "alfa_most__statika", "pending", 4, rel="statika.pdf")

    executor = _FakeExecutor()
    started, over_limit = projects_service.start_archive_indexing(db, [root], executor)

    assert (started, over_limit) == (1, 1)
    statuses = {d.slug: d.status for d in db.scalars(select(ProjectDocument))}
    assert statuses == {
        "alfa_most__tz": "processing",
        "alfa_most__statika": "pending",
    }


def test_pilot_build_archive_has_no_limit(db, tmp_path, monkeypatch):
    monkeypatch.setattr(limits, "PUBLIC_BUILD", False)
    root = tmp_path / "Alfa_most"
    root.mkdir()
    (root / "tz.pdf").write_bytes(b"%PDF-1.4 fake")
    _arc_doc(db, "alfa_most__tz", "pending", 4000, rel="tz.pdf")

    executor = _FakeExecutor()
    started, over_limit = projects_service.start_archive_indexing(db, [root], executor)

    assert (started, over_limit) == (1, 0)
