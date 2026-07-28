"""Тесты скана библиотеки: регистрация pending и усыновление готовых индексов."""

import json
import os
import shutil

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.core import index_store
from backend.core.database import Base
from backend.modules.documents.models import Document
from backend.modules.library.service import build_library_response, scan_library


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


def test_copied_folder_gets_fresh_id(db, tmp_path):
    # Папку скопировали вместе с .search_index → одинаковый folder_id.
    # Скан обязан перевыдать метку второй папке, иначе документы спутаются.
    from indexing.embeddings_index import EMBEDDING_MODEL

    lib_a = _make_library(tmp_path / "A", "most.pdf")
    index_store.ensure_meta(lib_a, EMBEDDING_MODEL)
    lib_b = _make_library(tmp_path / "B", "jiny.pdf")
    # Копируем meta.json из A в B (симулируем копирование папки).
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
    # После скана метки разные, а документы не спутаны.
    assert (
        index_store.read_meta(lib_a)["folder_id"]
        != index_store.read_meta(lib_b)["folder_id"]
    )
    slugs = {d.slug for d in db.scalars(select(Document)).all()}
    assert len(slugs) == 2


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


def test_unavailable_folder_does_not_crash(db, tmp_path):
    # Отвалившийся сетевой диск: скан и дерево живут, папка помечена.
    ok = _make_library(tmp_path / "A", "Norma.pdf")
    missing = tmp_path / "B"  # не существует

    summary = scan_library([ok, missing], db)
    assert summary.created == 1  # здоровая папка отсканирована

    response = build_library_response([ok, missing], db)
    names = [f.name for f in response.tree.folders]
    assert any("nedostupná" in n for n in names)


def test_same_physical_folder_twice_keeps_folder_id(db, tmp_path):
    # Одна папка под двумя путями (симлинк) — НЕ перевыдаём метку пинг-понгом.
    lib = _make_library(tmp_path / "A", "Norma.pdf")
    link = tmp_path / "link"
    link.symlink_to(lib)

    scan_library([lib, link], db)
    fid_before = index_store.read_meta(lib)["folder_id"]
    # Повторные обращения (дерево строит метки заново) не меняют метку.
    build_library_response([lib, link], db)
    build_library_response([lib, link], db)
    assert index_store.read_meta(lib)["folder_id"] == fid_before


@pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="root игнорирует права файлов — PermissionError не воспроизвести",
)
def test_readonly_folder_marks_docs_failed(db, tmp_path):
    # Read-only папка: .search_index не создать → раньше документ вечно висел
    # «čeká» без единой ошибки. Теперь — failed с чешской причиной.
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
    reason="root игнорирует права файлов — PermissionError не воспроизвести",
)
def test_readonly_folder_heals_stuck_pending(db, tmp_path):
    # Документ, застрявший в pending ДО фикса, рескан переводит в failed.
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
    # Документ завис pending (зарегистрирован до того, как коллега доиндексировал
    # общую папку). «Indexovat» должен усыновить готовый индекс, а не гнать
    # платный пайплайн заново.
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
    assert executor.calls == []  # пайплайн НЕ запускался
    db.refresh(doc)
    assert doc.status == "ready"
    assert doc.title == "ČSN Norma 123"


def test_pending_doc_without_index_still_submitted(db, tmp_path):
    # Гард от пере-усыновления: нет готового индекса — обычный запуск пайплайна.
    from backend.modules.library.service import start_indexing

    library = _make_library(tmp_path, "Norma.pdf")
    scan_library([library], db)

    executor = _FakeExecutor()
    submitted, _locked = start_indexing([library], db, executor)

    assert submitted == 1
    assert len(executor.calls) == 1
    doc = db.scalar(select(Document))
    assert doc.status == "processing"
