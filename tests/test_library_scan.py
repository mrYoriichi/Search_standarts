"""Тесты скана библиотеки: регистрация pending и усыновление готовых индексов."""

import json

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.core import index_store
from backend.core.database import Base
from backend.modules.documents.models import Document
from backend.modules.library.service import scan_library


@pytest.fixture
def db():
    """Чистая in-memory SQLite на каждый тест."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _make_library(folder, pdf_name: str):
    """Папка библиотеки с одним PDF (скан не открывает файл, важно имя)."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / pdf_name).write_bytes(b"%PDF-1.4 fake")
    return folder


def _make_index(library_path, slug: str, model: str, title: str | None = None):
    """Готовый индекс в .search_index: meta + chunks + embeddings (+ название)."""
    index_store.ensure_meta(library_path, model)
    d = index_store.doc_dir(library_path, slug)
    d.mkdir(parents=True)
    (d / "chunks.json").write_text("[]", encoding="utf-8")
    (d / "embeddings.json").write_text("{}", encoding="utf-8")
    if title:
        (d / "descriptions.json").write_text(
            json.dumps({"document_title": title}), encoding="utf-8"
        )


def _slug(library, filename_slug):
    """Ожидаемый scoped-slug документа в этой папке (метка папки + имя)."""
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
    # meta создаётся при первом скане; создаём заранее, чтобы знать slug.
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
    # Убираем embeddings.json — индекс неполный, пайплайн не был закончен.
    (index_store.doc_dir(library, slug) / "embeddings.json").unlink()
    summary = scan_library([library], db)
    assert (summary.created, summary.adopted) == (1, 0)


def test_same_filename_in_two_folders_are_distinct_docs(db, tmp_path):
    # Один и тот же файл "most.pdf" в двух папках → два разных документа.
    lib_a = _make_library(tmp_path / "A", "most.pdf")
    lib_b = _make_library(tmp_path / "B", "most.pdf")
    summary = scan_library([lib_a, lib_b], db)
    assert summary.created == 2
    assert summary.duplicates == []
    slugs = {d.slug for d in db.scalars(select(Document)).all()}
    assert slugs == {_slug(lib_a, "most"), _slug(lib_b, "most")}


def test_duplicate_within_one_folder_is_reported(db, tmp_path):
    # Два одноимённых файла в ОДНОЙ папке (в подпапках) — коллизия.
    lib = tmp_path / "lib"
    (lib / "x").mkdir(parents=True)
    (lib / "y").mkdir(parents=True)
    (lib / "x" / "most.pdf").write_bytes(b"%PDF-1.4 a")
    (lib / "y" / "most.pdf").write_bytes(b"%PDF-1.4 b")
    summary = scan_library([lib], db)
    assert summary.created == 0
    assert len(summary.duplicates) == 2
