"""Library scan tests: registering pending docs and adopting ready indexes."""

import json
import os
import shutil

import pytest

from backend.core import ui_messages
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.core import index_store
from backend.core.database import Base
from backend.modules.documents.models import Document
from backend.modules.library.service import build_library_response, scan_library


@pytest.fixture(autouse=True)
def czech_messages():
    """Tests assert Czech reference texts; the app default is now English."""
    ui_messages.set_language("cs")
    yield
    ui_messages.set_language("en")


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


def _make_index(library_path, slug: str, model: str, title: str | None = None):
    """Ready index in .search_index: meta + chunks + embeddings (+ title)."""
    index_store.ensure_meta(library_path, model)
    d = index_store.doc_dir(library_path, slug)
    d.mkdir(parents=True)
    (d / "chunks.json").write_text(
        json.dumps([{"chunk_id": f"{slug}_c001", "text": "obsah"}]), encoding="utf-8"
    )
    (d / "embeddings.json").write_text(
        json.dumps(
            {
                "model": model,
                "items": [{"chunk_id": f"{slug}_c001", "embedding": [0.1]}],
            }
        ),
        encoding="utf-8",
    )
    if title:
        (d / "descriptions.json").write_text(
            json.dumps({"document_title": title}), encoding="utf-8"
        )


def _slug(library, filename_slug):
    """Expected scoped slug of a document in this folder (folder label + name)."""
    fid = index_store.read_meta(library)["folder_id"]
    return index_store.scoped_slug(fid, filename_slug)


def test_new_pdf_becomes_pending(db, tmp_path):
    library = _make_library(tmp_path, "Norma.pdf")
    summary = scan_library([library], db)
    assert (summary.created, summary.adopted) == (1, 0)
    doc = db.scalar(select(Document).where(Document.slug == _slug(library, "norma")))
    assert doc.status == "pending"


def test_ready_index_is_adopted(db, tmp_path):
    from indexing.embeddings_index import EMBEDDING_MODEL

    library = _make_library(tmp_path, "Norma.pdf")
    # meta is created on the first scan; create it upfront to know the slug.
    index_store.ensure_meta(library, EMBEDDING_MODEL)
    slug = _slug(library, "norma")
    _make_index(library, slug, EMBEDDING_MODEL, title="ČSN Norma 123")
    summary = scan_library([library], db)
    assert (summary.created, summary.adopted) == (0, 1)
    doc = db.scalar(select(Document).where(Document.slug == slug))
    assert doc.status == "ready"
    assert doc.title == "ČSN Norma 123"


def test_foreign_model_index_is_not_adopted(db, tmp_path):
    library = _make_library(tmp_path, "Norma.pdf")
    index_store.ensure_meta(library, "some-other-model")
    slug = _slug(library, "norma")
    _make_index(library, slug, "some-other-model")
    summary = scan_library([library], db)
    assert (summary.created, summary.adopted) == (1, 0)


def test_incomplete_index_is_not_adopted(db, tmp_path):
    from indexing.embeddings_index import EMBEDDING_MODEL

    library = _make_library(tmp_path, "Norma.pdf")
    index_store.ensure_meta(library, EMBEDDING_MODEL)
    slug = _slug(library, "norma")
    _make_index(library, slug, EMBEDDING_MODEL)
    # Remove embeddings.json — the index is incomplete, pipeline never finished.
    (index_store.doc_dir(library, slug) / "embeddings.json").unlink()
    summary = scan_library([library], db)
    assert (summary.created, summary.adopted) == (1, 0)


def test_same_filename_in_two_folders_are_distinct_docs(db, tmp_path):
    # The same file "most.pdf" in two folders → two distinct documents.
    lib_a = _make_library(tmp_path / "A", "most.pdf")
    lib_b = _make_library(tmp_path / "B", "most.pdf")
    summary = scan_library([lib_a, lib_b], db)
    assert summary.created == 2
    assert summary.duplicates == []
    slugs = {d.slug for d in db.scalars(select(Document)).all()}
    assert slugs == {_slug(lib_a, "most"), _slug(lib_b, "most")}


def test_copied_folder_gets_fresh_id(db, tmp_path):
    # The folder was copied along with .search_index → identical folder_id.
    # Scan must re-issue the second folder's label, or documents get mixed up.
    from indexing.embeddings_index import EMBEDDING_MODEL

    lib_a = _make_library(tmp_path / "A", "most.pdf")
    index_store.ensure_meta(lib_a, EMBEDDING_MODEL)
    lib_b = _make_library(tmp_path / "B", "jiny.pdf")
    # Copy meta.json from A to B (simulating a folder copy).
    (index_store.index_root(lib_b)).mkdir(parents=True, exist_ok=True)
    shutil.copy(
        index_store.index_root(lib_a) / "meta.json",
        index_store.index_root(lib_b) / "meta.json",
    )
    assert (
        index_store.read_meta(lib_a)["folder_id"]
        == index_store.read_meta(lib_b)["folder_id"]
    )

    scan_library([lib_a, lib_b], db)
    # After the scan the labels differ and documents are not mixed up.
    assert (
        index_store.read_meta(lib_a)["folder_id"]
        != index_store.read_meta(lib_b)["folder_id"]
    )
    slugs = {d.slug for d in db.scalars(select(Document)).all()}
    assert len(slugs) == 2


def test_duplicate_within_one_folder_is_reported(db, tmp_path):
    # Two same-named files in ONE folder (in subfolders) — a collision.
    lib = tmp_path / "lib"
    (lib / "x").mkdir(parents=True)
    (lib / "y").mkdir(parents=True)
    (lib / "x" / "most.pdf").write_bytes(b"%PDF-1.4 a")
    (lib / "y" / "most.pdf").write_bytes(b"%PDF-1.4 b")
    summary = scan_library([lib], db)
    assert summary.created == 0
    assert len(summary.duplicates) == 2


def test_unavailable_folder_does_not_crash(db, tmp_path):
    # A dropped network drive: scan and tree stay alive, the folder is marked.
    ok = _make_library(tmp_path / "A", "Norma.pdf")
    missing = tmp_path / "B"  # does not exist

    summary = scan_library([ok, missing], db)
    assert summary.created == 1  # the healthy folder was scanned

    response = build_library_response([ok, missing], db)
    names = [f.name for f in response.tree.folders]
    assert any("nedostupná" in n for n in names)


def test_same_physical_folder_twice_keeps_folder_id(db, tmp_path):
    # One folder under two paths (symlink) — do NOT reissue the label ping-pong.
    lib = _make_library(tmp_path / "A", "Norma.pdf")
    link = tmp_path / "link"
    link.symlink_to(lib)

    scan_library([lib, link], db)
    fid_before = index_store.read_meta(lib)["folder_id"]
    # Repeated calls (the tree rebuilds labels) do not change the label.
    build_library_response([lib, link], db)
    build_library_response([lib, link], db)
    assert index_store.read_meta(lib)["folder_id"] == fid_before


@pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="root ignores file permissions — PermissionError not reproducible",
)
def test_readonly_folder_marks_docs_failed(db, tmp_path):
    # Read-only folder: .search_index cannot be created -> the document used
    # to hang in "čeká" forever without any error. Now — failed with a reason.
    library = _make_library(tmp_path / "lib", "Norma.pdf")
    os.chmod(library, 0o500)
    try:
        scan_library([library], db)
        doc = db.scalar(select(Document))
        assert doc.status == "failed"
        assert "zapisovat" in doc.error_message
    finally:
        os.chmod(library, 0o700)


@pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="root ignores file permissions — PermissionError not reproducible",
)
def test_readonly_folder_heals_stuck_pending(db, tmp_path):
    # A document stuck in pending BEFORE the fix is moved to failed by a rescan.
    library = _make_library(tmp_path / "lib", "Norma.pdf")
    db.add(
        Document(
            slug="norma", title="Norma", status="pending", relative_path="Norma.pdf"
        )
    )
    db.commit()
    os.chmod(library, 0o500)
    try:
        scan_library([library], db)
        doc = db.scalar(select(Document).where(Document.slug == "norma"))
        assert doc.status == "failed"
        assert "zapisovat" in doc.error_message
    finally:
        os.chmod(library, 0o700)


class _FakeExecutor:
    def __init__(self):
        self.calls = []

    def submit(self, fn, *args, **kwargs):
        self.calls.append((fn, args))


def test_pending_doc_with_ready_shared_index_is_adopted(db, tmp_path):
    # A document hung in pending (registered before a colleague finished
    # indexing the shared folder). "Indexovat" must adopt the ready index,
    # not run the paid pipeline again.
    from indexing.embeddings_index import EMBEDDING_MODEL

    from backend.modules.library.service import start_indexing

    library = _make_library(tmp_path, "Norma.pdf")
    scan_library([library], db)
    slug = _slug(library, "norma")
    doc = db.scalar(select(Document).where(Document.slug == slug))
    assert doc.status == "pending"
    _make_index(library, slug, EMBEDDING_MODEL, title="ČSN Norma 123")

    executor = _FakeExecutor()
    submitted, locked = start_indexing([library], db, executor)

    assert (submitted, locked) == (0, [])
    assert executor.calls == []  # the pipeline did NOT run
    db.refresh(doc)
    assert doc.status == "ready"
    assert doc.title == "ČSN Norma 123"


def test_pending_doc_without_index_still_submitted(db, tmp_path):
    # Guard against over-adoption: no ready index — a normal pipeline run.
    from backend.modules.library.service import start_indexing

    library = _make_library(tmp_path, "Norma.pdf")
    scan_library([library], db)

    executor = _FakeExecutor()
    submitted, _locked = start_indexing([library], db, executor)

    assert submitted == 1
    assert len(executor.calls) == 1
    doc = db.scalar(select(Document))
    assert doc.status == "processing"
