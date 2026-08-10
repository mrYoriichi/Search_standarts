"""Воркер parse: протокол заданий и событий (parse подменён — без docling).

Задания приходят JSON-строками из stdin, события уходят в stdout.
Ошибка одного задания не убивает цикл; тишина idle_timeout — выход.
"""

import io
import json
import threading
from typing import Callable

import pytest

import pipeline.parse
from pipeline import parse_worker

JOB = {
    "slug": "f1__doc1",
    "pdf_path": "/pdfs/doc1.pdf",
    "doc_dir": "/idx/doc1",
    "pages_dir": "/tmp/pages",
}


def fake_process(
    pdf_name: str,
    pdf_path: str | None = None,
    doc_dir: object = None,
    document_id: str | None = None,
    pages_dir: object = None,
    on_text_pages: Callable | None = None,
    on_drawing_page: Callable | None = None,
) -> None:
    on_text_pages(2)
    on_drawing_page(1, 3)


def run_worker(
    jobs: list[dict], monkeypatch: pytest.MonkeyPatch, process: Callable = fake_process
) -> list[dict]:
    monkeypatch.setattr(pipeline.parse, "process", process)
    inp = io.StringIO("".join(json.dumps(j) + "\n" for j in jobs))
    out = io.StringIO()
    parse_worker.serve(inp, out)
    return [json.loads(line) for line in out.getvalue().splitlines()]


def test_job_emits_progress_and_done(monkeypatch: pytest.MonkeyPatch) -> None:
    events = run_worker([JOB], monkeypatch)
    assert events == [
        {"event": "text_pages", "total": 2},
        {"event": "drawing_page", "done": 1, "total": 3},
        {"event": "done"},
    ]


def test_passes_job_fields_to_parse(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict = {}

    def spy(pdf_name: str, **kwargs: object) -> None:
        seen["pdf_name"] = pdf_name
        seen.update(kwargs)

    run_worker([JOB], monkeypatch, process=spy)
    assert seen["pdf_name"] == "f1__doc1"
    assert seen["pdf_path"] == "/pdfs/doc1.pdf"
    # document_id = slug: артефакты должны нести scoped-slug из БД.
    assert seen["document_id"] == "f1__doc1"
    assert str(seen["doc_dir"]) == "/idx/doc1"
    assert str(seen["pages_dir"]) == "/tmp/pages"


def test_error_reports_type_and_text_and_continues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def flaky(pdf_name: str, **kwargs: object) -> None:
        if pdf_name == "bad":
            raise ValueError("boom")

    events = run_worker([{**JOB, "slug": "bad"}, JOB], monkeypatch, process=flaky)
    # Классификация текста ошибки — дело родителя (там живёт язык UI),
    # воркер шлёт сырые тип и текст.
    assert events == [
        {"event": "error", "type": "ValueError", "text": "boom"},
        {"event": "done"},
    ]


def test_eof_stops_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    # Пустой stdin (родитель закрыл канал) — serve возвращается сразу.
    events = run_worker([], monkeypatch)
    assert events == []


def test_idle_timeout_exits() -> None:
    class BlockingInput:
        """stdin, из которого никогда ничего не приходит."""

        def __iter__(self) -> "BlockingInput":
            return self

        def __next__(self) -> str:
            threading.Event().wait(5)
            raise StopIteration

    out = io.StringIO()
    # Вернулся сам по таймауту — значит очередь «кончилась» и процесс умрёт.
    parse_worker.serve(BlockingInput(), out, idle_timeout=0.05)
    assert out.getvalue() == ""
