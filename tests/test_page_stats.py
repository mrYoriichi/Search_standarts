"""Page counters + removal of the hard page limit (decision 2026-08-06).

The public-build hard limit (5000 pages) is gone: it silently did not
apply to the search pool anyway (the pool takes everything on disk), and
the target scenario — connecting a big shared company folder — was the
first thing it broke. Instead the UI shows a live ready-page counter; a
memory estimate with a threshold comes after a measurement on a real
library. These tests pin both halves: counters count only ready rows,
and neither scan adoption nor indexing refuses documents by volume.
"""

import json

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.core import index_store, page_stats
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


# --- Counters ----------------------------------------------------------------


def test_counters_count_only_ready_rows_per_pool(db):
    _lib_doc(db, "a", "ready", 100)
    _lib_doc(db, "b", "processing", 50)  # not in the search pool yet
    _lib_doc(db, "c", "pending", 999)
    _lib_doc(db, "d", "ready", None)  # legacy row without a counter
    _arc_doc(db, "p__tz", "ready", 30)
    _arc_doc(db, "p__st", "failed", 70, rel="statika.pdf")
    assert page_stats.library_pages(db) == 100
    assert page_stats.archive_pages(db) == 30


# --- Adoption during scan: volume never blocks -------------------------------


def test_scan_adopts_and_stores_pages(db, tmp_path, monkeypatch):
    monkeypatch.setattr(library_service, "count_pages", lambda p: 5)
    library, slug = _make_indexed_library(tmp_path, "Norma.pdf")

    summary = library_service.scan_library([library], db)

    doc = db.scalar(select(Document).where(Document.slug == slug))
    assert doc.status == "ready"
    assert doc.page_count == 5
    assert summary.adopted == 1


def test_scan_adopts_no_matter_the_volume(db, tmp_path, monkeypatch):
    # Before 2026-08-06 a big ready index was left pending ("over limit").
    monkeypatch.setattr(library_service, "count_pages", lambda p: 99_999)
    library, slug = _make_indexed_library(tmp_path, "Norma.pdf")

    summary = library_service.scan_library([library], db)

    doc = db.scalar(select(Document).where(Document.slug == slug))
    assert doc.status == "ready"
    assert doc.page_count == 99_999
    assert summary.adopted == 1


# --- Library indexing: volume never blocks -----------------------------------


def test_start_indexing_sends_everything(db, tmp_path, monkeypatch):
    from indexing.embeddings_index import EMBEDDING_MODEL

    monkeypatch.setattr(library_service, "count_pages", lambda p: 5_000)
    library = tmp_path / "lib"
    library.mkdir()
    index_store.ensure_meta(library, EMBEDDING_MODEL)
    fid = index_store.read_meta(library)["folder_id"]
    for name in ("A.pdf", "B.pdf"):
        (library / name).write_bytes(b"%PDF-1.4 fake")
        db.add(
            Document(
                slug=index_store.scoped_slug(fid, name[:-4].lower()),
                title=name,
                status="pending",
                relative_path=name,
            )
        )
    db.commit()

    executor = _FakeExecutor()
    started, locked = library_service.start_indexing([library], db, executor)

    assert (started, locked) == (2, [])
    docs = db.scalars(select(Document)).all()
    assert {d.status for d in docs} == {"processing"}
    assert {d.page_count for d in docs} == {5_000}  # counter data still filled
    assert len(executor.calls) == 2


# --- Archive indexing: volume never blocks -----------------------------------


def test_archive_indexing_sends_everything(db, tmp_path):
    root = tmp_path / "Alfa_most"
    root.mkdir()
    (root / "tz.pdf").write_bytes(b"%PDF-1.4 fake")
    (root / "statika.pdf").write_bytes(b"%PDF-1.4 fake")
    _arc_doc(db, "alfa_most__tz", "pending", 4_000, rel="tz.pdf")
    _arc_doc(db, "alfa_most__statika", "pending", 4_000, rel="statika.pdf")

    executor = _FakeExecutor()
    started, _locked = projects_service.start_archive_indexing(db, [root], executor)

    assert started == 2
    statuses = {d.slug: d.status for d in db.scalars(select(ProjectDocument))}
    assert statuses == {
        "alfa_most__tz": "processing",
        "alfa_most__statika": "processing",
    }
