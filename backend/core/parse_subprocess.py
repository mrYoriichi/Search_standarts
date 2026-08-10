"""Запуск и обслуживание воркера parse (pipeline/parse_worker.py).

Один долгоживущий дочерний процесс на всё приложение: первый документ
очереди его поднимает, дальше задания идут по одному (parse и так
сериализован шлюзом cpu_gate). После 60 с тишины воркер выходит сам —
ОС забирает гигабайты моделей, а основной процесс никогда их и не
грузит. Смерть воркера родитель замечает при следующем задании и
поднимает нового.
"""

import json
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable

from backend.core.errors import classify_by_name
from backend.core.ui_messages import msg

_lock = threading.Lock()
_worker: subprocess.Popen | None = None


class ParseFailedError(Exception):
    """Parse в воркере не удался; str(exc) — готовый текст для UI."""


def _worker_command() -> list[str]:
    if getattr(sys, "frozen", False):
        # В сборке отдельного python.exe нет — exe запускает сам себя
        # со служебным флагом (run_app.main его перехватывает).
        return [sys.executable, "--parse-worker"]
    return [sys.executable, "-m", "pipeline.parse_worker"]


def _drain_stderr(proc: subprocess.Popen) -> None:
    # stderr воркера (печать пайплайна, трейсбеки) — в лог родителя.
    # Отдельный поток: невычитанный пайп заполнится и заблокирует воркер.
    for line in proc.stderr:
        print(f"[parse] {line.rstrip()}", file=sys.stderr)


def _spawn() -> subprocess.Popen:
    creationflags = 0
    if sys.platform == "win32":
        # Без флага у каждого воркера мигало бы чёрное окно консоли.
        creationflags = subprocess.CREATE_NO_WINDOW
    proc = subprocess.Popen(
        _worker_command(),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=creationflags,
    )
    # Жизненный цикл воркера — в app.log: без этих строк зависание
    # (инцидент 2026-08-10: воркер в сборке жив, но молчит — подозрение
    # на EDR/антивирус) неотличимо от чего угодно другого.
    print(f"[parse] spawned worker pid={proc.pid}", file=sys.stderr)
    threading.Thread(target=_drain_stderr, args=(proc,), daemon=True).start()
    return proc


def _forget(proc: subprocess.Popen) -> None:
    global _worker
    if proc.poll() is None:
        proc.kill()
    proc.wait()
    print(f"[parse] worker pid={proc.pid} gone (rc={proc.returncode})", file=sys.stderr)
    if _worker is proc:
        _worker = None


def _send_job(job: dict) -> subprocess.Popen:
    """Отдать задание живому воркеру (поднять нового, если умер)."""
    global _worker
    line = json.dumps(job) + "\n"
    for _attempt in range(2):
        if _worker is None or _worker.poll() is not None:
            if _worker is not None:
                _worker.wait()  # похоронить зомби перед заменой
            _worker = _spawn()
        try:
            _worker.stdin.write(line)
            _worker.stdin.flush()
            print(f"[parse] job sent: {job['slug']}", file=sys.stderr)
            return _worker
        except OSError:
            # Воркер умер по idle-таймауту ровно между poll() и write —
            # второй круг поднимет нового.
            _forget(_worker)
    raise ParseFailedError(msg("err.parse_crashed"))


def run_parse(
    slug: str,
    pdf_path: str | None,
    doc_dir: Path,
    pages_dir: Path | None = None,
    on_text_pages: Callable[[int], None] | None = None,
    on_drawing_page: Callable[[int, int], None] | None = None,
) -> None:
    """Прогнать parse одного документа в воркере (блокирует до конца).

    События прогресса транслируются в те же колбэки, что были у прямого
    вызова parse.process. pages_dir=None (архив) — скриншоты в
    doc_dir/pages. Ошибка → ParseFailedError с готовым текстом.
    """
    job = {
        "slug": slug,
        "pdf_path": pdf_path,
        "doc_dir": str(doc_dir),
        "pages_dir": str(pages_dir) if pages_dir else None,
    }
    with _lock:
        proc = _send_job(job)
        while True:
            line = proc.stdout.readline()
            if not line:
                # EOF: воркер умер посреди задания (bad_alloc, segfault).
                # Раньше это роняло ВСЁ приложение — теперь только документ.
                _forget(proc)
                raise ParseFailedError(msg("err.parse_crashed"))
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                # Нативная библиотека написала в stdout мимо редиректа
                # воркера — не протокол, просто в лог.
                print(f"[parse] {line.rstrip()}", file=sys.stderr)
                continue
            kind = event.get("event")
            if kind == "text_pages" and on_text_pages:
                on_text_pages(event["total"])
            elif kind == "drawing_page" and on_drawing_page:
                on_drawing_page(event["done"], event["total"])
            elif kind == "done":
                return
            elif kind == "error":
                raise ParseFailedError(classify_by_name(event["type"], event["text"]))


def stop_worker() -> None:
    """Убить воркера при выходе приложения — сирота держал бы гигабайты.

    Без _lock: выход из трея не должен ждать конца часового OCR.
    """
    proc = _worker
    if proc is not None and proc.poll() is None:
        proc.kill()
