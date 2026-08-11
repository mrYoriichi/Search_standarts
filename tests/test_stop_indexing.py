"""Остановка индексации (кнопки ⏹, решение 2026-08-11).

Кооперативная: пайплайн проверяет реестр отмены (backend/core/cancel)
в безопасных точках — между стадиями, между страницами describe, между
событиями parse — и выходит через IndexingCancelled. Документ
возвращается в «čeká», чекпоинты остаются, продолжение бесплатно.
"""

import json
import sys
from pathlib import Path
from typing import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.core import cancel, parse_subprocess
from backend.core.cancel import IndexingCancelled
from backend.core.database import Base
from backend.modules.documents.models import Document
from backend.modules.documents.pipeline import run_pipeline
from backend.modules.projects.models import ProjectDocument


@pytest.fixture
def db_engine():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def db(db_engine, monkeypatch):
    """Сессия + подмена SessionLocal: пайплайн открывает свою сессию сам."""
    maker = sessionmaker(bind=db_engine)
    import backend.modules.documents.pipeline as lib_pipeline
    import backend.modules.projects.pipeline as arc_pipeline

    monkeypatch.setattr(lib_pipeline, "SessionLocal", maker)
    monkeypatch.setattr(arc_pipeline, "SessionLocal", maker)
    session = maker()
    yield session
    session.close()


@pytest.fixture(autouse=True)
def clean_registry() -> Iterator[None]:
    yield
    cancel._requested.clear()
    cancel._running.clear()
    parse_subprocess.stop_worker()
    parse_subprocess._worker = None
    parse_subprocess._worker_blocked = False


# --- реестр + run_parse ---


def test_registry_roundtrip():
    cancel.request("a")
    assert cancel.requested("a")
    cancel.mark_done("a")
    assert not cancel.requested("a")


SLOW_AFTER_FIRST_EVENT = """
import json, sys, time
print(json.dumps({"event": "ready"}), flush=True)
sys.stdin.readline()
print(json.dumps({"event": "text_pages", "total": 5}), flush=True)
time.sleep(600)
"""


def use_worker(monkeypatch: pytest.MonkeyPatch, script: str) -> None:
    monkeypatch.setattr(
        parse_subprocess, "_worker_command", lambda: [sys.executable, "-c", script]
    )


def test_run_parse_cancel_between_events(monkeypatch: pytest.MonkeyPatch) -> None:
    # ⏹ во время parse: после очередного события видим флаг — воркер
    # убит (протокол не засоряется недоеденным заданием), IndexingCancelled.
    use_worker(monkeypatch, SLOW_AFTER_FIRST_EVENT)
    with pytest.raises(IndexingCancelled):
        parse_subprocess.run_parse(
            "f1__doc1",
            "/pdfs/doc1.pdf",
            Path("/idx/doc1"),
            should_cancel=lambda: True,
        )
    assert parse_subprocess._worker is None


CRASH_MID_JOB = """
import json, sys
print(json.dumps({"event": "ready"}), flush=True)
sys.stdin.readline()
"""


def test_run_parse_eof_with_cancel_is_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # kill_if_parsing убивает воркер посреди Docling: родитель получает
    # EOF, но при взведённом флаге это остановка, а не err.parse_crashed.
    use_worker(monkeypatch, CRASH_MID_JOB)
    with pytest.raises(IndexingCancelled):
        parse_subprocess.run_parse(
            "f1__doc1",
            "/pdfs/doc1.pdf",
            Path("/idx/doc1"),
            should_cancel=lambda: True,
        )


# --- пайплайн библиотеки ---


def _lib_doc(db, slug: str) -> Document:
    doc = Document(slug=slug, title=slug, status="processing", relative_path="a.pdf")
    db.add(doc)
    db.commit()
    return doc


def test_queued_cancel_exits_before_any_stage(db, tmp_path):
    # ⏹ по документу в очереди: пайплайн стартует, видит флаг и выходит,
    # не дойдя даже до parse; документ снова čeká, флаг снят.
    doc = _lib_doc(db, "f1__doc1")
    cancel.request("f1__doc1")
    run_pipeline("f1__doc1", str(tmp_path / "a.pdf"), tmp_path / "idx")
    db.refresh(doc)
    assert doc.status == "pending"
    assert not cancel.requested("f1__doc1")


def test_cancel_after_parse_skips_describe_and_returns_pending(
    db, tmp_path, monkeypatch
):
    # ⏹ прилетел во время parse: describe уже не запускается, документ
    # возвращается в čeká (НЕ failed) — чекпоинты целы.
    doc = _lib_doc(db, "f1__doc1")

    def fake_parse(slug, *a, **kw):
        cancel.request(slug)  # юзер нажал ⏹, пока шёл parse

    monkeypatch.setattr(parse_subprocess, "run_parse", fake_parse)
    import pipeline.describe as describe_step

    def boom(*a, **kw):
        raise AssertionError("describe must not run after cancel")

    monkeypatch.setattr(describe_step, "process", boom)
    run_pipeline("f1__doc1", str(tmp_path / "a.pdf"), tmp_path / "idx")
    db.refresh(doc)
    assert doc.status == "pending"
    assert doc.error_message is None
    assert not cancel.requested("f1__doc1")


# --- пайплайн архива ---


def test_archive_queued_cancel_returns_pending(db, tmp_path):
    doc = ProjectDocument(
        slug="p__tz",
        project="p",
        relative_path="tz.pdf",
        doc_type="text",
        page_count=1,
        status="processing",
    )
    db.add(doc)
    db.commit()
    cancel.request("p__tz")

    from backend.modules.projects.pipeline import _run_project_pipeline

    _run_project_pipeline("p__tz", str(tmp_path / "tz.pdf"), str(tmp_path))
    db.refresh(doc)
    assert doc.status == "pending"
    assert not cancel.requested("p__tz")


# --- эндпоинт остановки (сервисный слой) ---


def test_stop_queued_document_returns_pending_immediately(db):
    # Документ в очереди executor (processing, но пайплайн не начался):
    # ⏹ возвращает его в čeká сразу, не дожидаясь его очереди.
    from backend.core import progress
    from backend.modules.documents import service as doc_service
    from backend.core.ui_messages import msg

    doc = _lib_doc(db, "f1__doc1")
    progress.set_progress("f1__doc1", msg("progress.queued"))

    doc_service.stop_document(db, "f1__doc1")

    db.refresh(doc)
    assert doc.status == "pending"
    assert progress.get_progress("f1__doc1") is None
    assert cancel.requested("f1__doc1")  # задача executor выйдет молча


def test_stop_running_document_flags_and_waits(db):
    # Документ реально работает: статус не трогаем (пайплайн сам дойдёт
    # до безопасной точки), но флаг взведён и в прогрессе «zastavuje se».
    from backend.core import progress
    from backend.modules.documents import service as doc_service
    from backend.core.ui_messages import msg

    doc = _lib_doc(db, "f1__doc1")
    cancel.mark_running("f1__doc1")

    doc_service.stop_document(db, "f1__doc1")

    db.refresh(doc)
    assert doc.status == "processing"
    assert cancel.requested("f1__doc1")
    assert progress.get_progress("f1__doc1") == msg("progress.stopping")
    progress.clear_progress("f1__doc1")


def test_stop_archive_queued_document(db):
    from backend.core import progress
    from backend.modules.projects import service as proj_service
    from backend.core.ui_messages import msg

    doc = ProjectDocument(
        slug="p__tz",
        project="p",
        relative_path="tz.pdf",
        doc_type="text",
        page_count=1,
        status="processing",
    )
    db.add(doc)
    db.commit()
    progress.set_progress("p__tz", msg("progress.queued"))

    proj_service.stop_document(db, "p__tz")

    db.refresh(doc)
    assert doc.status == "pending"
    assert progress.get_progress("p__tz") is None


def test_stop_non_processing_document_is_noop(db):
    from backend.modules.documents import service as doc_service

    doc = _lib_doc(db, "f1__doc1")
    doc.status = "ready"
    db.commit()

    doc_service.stop_document(db, "f1__doc1")

    db.refresh(doc)
    assert doc.status == "ready"
    assert not cancel.requested("f1__doc1")


# --- describe: отмена между страницами ---


def test_describe_cancels_between_pages(tmp_path, monkeypatch):
    from pipeline import describe as describe_step

    doc_dir = tmp_path / "doc"
    pages_dir = doc_dir / "pages"
    pages_dir.mkdir(parents=True)
    document = {
        "document_id": "d1",
        "document_name": "d1.pdf",
        "pages": [
            {
                "page_number": 1,
                "page_text": "",
                "blocks": [{"block_id": "p1_b01", "type": "figure"}],
            }
        ],
    }
    (doc_dir / "document.json").write_text(json.dumps(document), encoding="utf-8")
    (pages_dir / "p001.png").write_bytes(b"fake")

    monkeypatch.setattr(
        describe_step,
        "extract_document_metadata",
        lambda *a, **kw: ({"title": "t", "summary": "s"}, 0, 0),
    )
    monkeypatch.setattr(
        describe_step,
        "describe_page_visuals",
        lambda *a, **kw: ({"p1_b01": "desc"}, 0, 0),
    )
    with pytest.raises(IndexingCancelled):
        describe_step.process(
            "d1", doc_dir=doc_dir, pages_dir=pages_dir, should_cancel=lambda: True
        )
    # Чекпоинт с метаданными сохранён — остановка не теряет оплаченное.
    saved = json.loads((doc_dir / "descriptions.json").read_text(encoding="utf-8"))
    assert saved["document_title"] == "t"
