"""Спавнер воркера parse: реальные подпроцессы, но воркер подменён
крошечными скриптами (без docling) через _worker_command.
"""

import json
import sys
from pathlib import Path
from typing import Iterator

import pytest

from backend.core import parse_subprocess
from backend.core.parse_subprocess import ParseFailedError, run_parse
from backend.core.ui_messages import msg

# Скрипты-имитации воркера (python -c). Протокол — как у настоящего:
# первым событием уходит ready (рукопожатие со спавнером).
HAPPY = """
import json, sys
print(json.dumps({"event": "ready"}), flush=True)
for line in sys.stdin:
    json.loads(line)
    print(json.dumps({"event": "text_pages", "total": 5}), flush=True)
    print(json.dumps({"event": "drawing_page", "done": 1, "total": 2}), flush=True)
    print(json.dumps({"event": "done"}), flush=True)
"""

ERROR = """
import json, sys
print(json.dumps({"event": "ready"}), flush=True)
for line in sys.stdin:
    json.loads(line)
    print(json.dumps({"event": "error", "type": "PdfiumError", "text": "password required"}), flush=True)
"""

CRASH_MID_JOB = """
import json, sys
print(json.dumps({"event": "ready"}), flush=True)
sys.stdin.readline()
"""

ONE_JOB_THEN_EXIT = """
import json, sys
print(json.dumps({"event": "ready"}), flush=True)
sys.stdin.readline()
print(json.dumps({"event": "done"}), flush=True)
"""

GARBAGE_THEN_DONE = """
import json, sys
print("native library noise", flush=True)
print(json.dumps({"event": "ready"}), flush=True)
for line in sys.stdin:
    print("native library noise", flush=True)
    print(json.dumps({"event": "done"}), flush=True)
"""

# Замёрзший воркер: процесс жив, но не исполняет ни строки протокола —
# так выглядит дочерний exe, остановленный EDR (инцидент 2026-08-10).
BLOCKED = """
import time
time.sleep(600)
"""

# Воркер ожил (ready), взял задание — и замёрз на импорте ML-стека:
# ровно картина app.log 2026-08-11 (worker ready + job received, а
# «ML stack imported» так и не пришёл).
READY_THEN_FREEZE = """
import json, sys, time
print(json.dumps({"event": "ready"}), flush=True)
sys.stdin.readline()
time.sleep(600)
"""


@pytest.fixture(autouse=True)
def clean_worker() -> Iterator[None]:
    yield
    parse_subprocess.stop_worker()
    parse_subprocess._worker = None
    parse_subprocess._worker_blocked = False


def use_worker(monkeypatch: pytest.MonkeyPatch, script: str) -> None:
    monkeypatch.setattr(
        parse_subprocess, "_worker_command", lambda: [sys.executable, "-c", script]
    )


def call(**callbacks: object) -> None:
    run_parse(
        "f1__doc1", "/pdfs/doc1.pdf", Path("/idx/doc1"), Path("/tmp/pages"), **callbacks
    )


def test_progress_events_reach_callbacks(monkeypatch: pytest.MonkeyPatch) -> None:
    use_worker(monkeypatch, HAPPY)
    seen: list[tuple] = []
    call(
        on_text_pages=lambda total: seen.append(("text", total)),
        on_drawing_page=lambda done, total: seen.append(("drawing", done, total)),
    )
    assert seen == [("text", 5), ("drawing", 1, 2)]


def test_worker_is_reused_between_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    use_worker(monkeypatch, HAPPY)
    call()
    first_pid = parse_subprocess._worker.pid
    call()
    # Один и тот же процесс — модели не грузятся заново на каждый документ.
    assert parse_subprocess._worker.pid == first_pid


def test_error_event_becomes_localized_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_worker(monkeypatch, ERROR)
    with pytest.raises(ParseFailedError) as exc_info:
        call()
    # Тип+текст классифицируются у родителя: PdfiumError + "password".
    assert str(exc_info.value) == msg("err.pdf_password")


def test_crash_mid_job_fails_document_not_app(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_worker(monkeypatch, CRASH_MID_JOB)
    with pytest.raises(ParseFailedError) as exc_info:
        call()
    assert str(exc_info.value) == msg("err.parse_crashed")
    assert parse_subprocess._worker is None  # мёртвый воркер забыт


def test_dead_worker_is_respawned_for_next_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Воркер умер между заданиями (idle-таймаут) — следующее задание
    # молча поднимает нового.
    use_worker(monkeypatch, ONE_JOB_THEN_EXIT)
    call()
    first_pid = parse_subprocess._worker.pid
    parse_subprocess._worker.wait(timeout=5)  # скрипт вышел сам
    call()
    assert parse_subprocess._worker.pid != first_pid


def test_non_json_stdout_lines_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    use_worker(monkeypatch, GARBAGE_THEN_DONE)
    call()  # не упало и дождалось done


def test_blocked_worker_falls_back_to_in_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Воркер не прислал ready за таймаут (EDR заморозил процесс) —
    # документ парсится в родителе, замёрзший процесс убит.
    use_worker(monkeypatch, BLOCKED)
    monkeypatch.setattr(parse_subprocess, "READY_TIMEOUT_S", 0.5)
    fallback: list[tuple] = []
    monkeypatch.setattr(
        parse_subprocess, "_parse_in_process", lambda *a: fallback.append(a)
    )
    call()
    assert len(fallback) == 1
    assert parse_subprocess._worker is None  # замёрзший процесс убит
    assert parse_subprocess._worker_blocked


def test_blocked_worker_not_respawned_for_next_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Один раз не дождались ready — до перезапуска приложения воркер
    # больше не спавнится (иначе каждый документ ждал бы таймаут).
    use_worker(monkeypatch, BLOCKED)
    monkeypatch.setattr(parse_subprocess, "READY_TIMEOUT_S", 0.5)
    fallback: list[tuple] = []
    monkeypatch.setattr(
        parse_subprocess, "_parse_in_process", lambda *a: fallback.append(a)
    )
    spawns: list[int] = []
    real_spawn = parse_subprocess._spawn

    def counting_spawn():
        spawns.append(1)
        return real_spawn()

    monkeypatch.setattr(parse_subprocess, "_spawn", counting_spawn)
    call()
    call()
    assert len(fallback) == 2
    assert len(spawns) == 1


def test_frozen_import_falls_back_to_in_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # ready пришёл, задание ушло, но ни одного события за таймаут (EDR
    # душит первый импорт docling/torch) — воркер убит, документ
    # парсится в родителе, воркер больше не спавнится.
    use_worker(monkeypatch, READY_THEN_FREEZE)
    monkeypatch.setattr(parse_subprocess, "FIRST_EVENT_TIMEOUT_S", 0.5)
    fallback: list[tuple] = []
    monkeypatch.setattr(
        parse_subprocess, "_parse_in_process", lambda *a: fallback.append(a)
    )
    call()
    assert len(fallback) == 1
    assert parse_subprocess._worker is None  # замёрзший процесс убит
    assert parse_subprocess._worker_blocked


def test_job_line_is_valid_json_with_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    # Эхо-воркер возвращает задание обратно текстом ошибки — так видно,
    # что именно уехало через границу процесса (чешские пути и т.п.).
    echo = (
        "import json, sys\n"
        'print(json.dumps({"event": "ready"}), flush=True)\n'
        "job = json.loads(sys.stdin.readline())\n"
        'print(json.dumps({"event": "error", "type": "EchoError",'
        ' "text": json.dumps(job, sort_keys=True)}), flush=True)\n'
    )
    use_worker(monkeypatch, echo)
    with pytest.raises(ParseFailedError) as exc_info:
        run_parse("sí__čertův", "/pdfs/čertův most.pdf", Path("/idx/č"), Path("/tmp/p"))
    echoed = json.loads(str(exc_info.value).split(": ", 1)[1])
    assert echoed == {
        "slug": "sí__čertův",
        "pdf_path": "/pdfs/čertův most.pdf",
        "doc_dir": "/idx/č",
        "pages_dir": "/tmp/p",
    }
