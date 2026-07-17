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


def _make_library(tmp_path, pdf_name: str):
    """Папка библиотеки с одним PDF (скан не открывает файл, важно имя)."""
    (tmp_path / pdf_name).write_bytes(b"%PDF-1.4 fake")
    return tmp_path


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


def test_new_pdf_becomes_pending(db, tmp_path):
    library = _make_library(tmp_path, "Norma.pdf")
    summary = scan_library(library, db)
    assert (summary.created, summary.adopted) == (1, 0)
    doc = db.scalar(select(Document).where(Document.slug == "norma"))
    assert doc.status == "pending"


def test_ready_index_is_adopted(db, tmp_path):
    from indexing.embeddings_index import EMBEDDING_MODEL

    library = _make_library(tmp_path, "Norma.pdf")
    _make_index(library, "norma", EMBEDDING_MODEL, title="ČSN Norma 123")
    summary = scan_library(library, db)
    assert (summary.created, summary.adopted) == (0, 1)
    doc = db.scalar(select(Document).where(Document.slug == "norma"))
    assert doc.status == "ready"
    assert doc.title == "ČSN Norma 123"


def test_foreign_model_index_is_not_adopted(db, tmp_path):
    library = _make_library(tmp_path, "Norma.pdf")
    _make_index(library, "norma", "some-other-model")
    summary = scan_library(library, db)
    assert (summary.created, summary.adopted) == (1, 0)
    doc = db.scalar(select(Document).where(Document.slug == "norma"))
    assert doc.status == "pending"


def test_incomplete_index_is_not_adopted(db, tmp_path):
    from indexing.embeddings_index import EMBEDDING_MODEL

    library = _make_library(tmp_path, "Norma.pdf")
    _make_index(library, "norma", EMBEDDING_MODEL)
    # Убираем embeddings.json — индекс неполный, пайплайн не был закончен.
    (index_store.doc_dir(library, "norma") / "embeddings.json").unlink()
    summary = scan_library(library, db)
    assert (summary.created, summary.adopted) == (1, 0)
