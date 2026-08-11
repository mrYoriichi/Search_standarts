"""Запуск и обслуживание воркера parse (pipeline/parse_worker.py).

Один долгоживущий дочерний процесс на всё приложение: первый документ
очереди его поднимает, дальше задания идут по одному (parse и так
сериализован шлюзом cpu_gate). После 60 с тишины воркер выходит сам —
ОС забирает гигабайты моделей, а основной процесс никогда их и не
грузит. Смерть воркера родитель замечает при следующем задании и
поднимает нового.
"""

import json
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable

import psutil

from backend.core.errors import classify_by_name
from backend.core.ui_messages import msg

# Сколько ждать событие ready от свежего воркера. Здоровый шлёт его
# сразу после старта (импорты лаунчера — секунды); замороженный
# EDR/антивирусом процесс не шлёт никогда (инцидент 2026-08-10).
READY_TIMEOUT_S = 60.0
# Ожидание ПЕРВОГО события после отправки задания — по прогрессу, не по
# секундомеру: до него воркер грузит docling/torch, и живой процесс
# постоянно растёт по памяти. Память стоит NO_PROGRESS_TIMEOUT_S подряд
# при полной тишине = заморожен EDR (лог 2026-08-11: ready и job
# received пришли за секунду, дальше 0% CPU и ни байта).
# FIRST_EVENT_TIMEOUT_S — абсолютный потолок на любой случай.
NO_PROGRESS_TIMEOUT_S = 45.0
FIRST_EVENT_TIMEOUT_S = 600.0
_POLL_SLICE_S = 5.0
_RSS_GROWTH_MIN = 1024 * 1024  # +1 МБ между замерами = «жив, грузится»

_lock = threading.Lock()
_worker: subprocess.Popen | None = None
# Воркер не ожил ни разу — до перезапуска приложения парсим в родителе,
# иначе каждый документ ждал бы таймаут заново.
_worker_blocked = False


class ParseFailedError(Exception):
    """Parse в воркере не удался; str(exc) — готовый текст для UI."""


class _WorkerBlockedError(Exception):
    """Свежий воркер не прислал ready за таймаут — процесс заморожен."""


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


def _wait_ready(proc: subprocess.Popen) -> bool:
    """Дождаться события ready от свежего воркера (False = таймаут/EOF).

    Читает stdout в отдельном потоке: у пайпов нет readline с таймаутом.
    Поток читает РОВНО до ready и останавливается — события заданий
    остаются главному циклу run_parse.
    """
    got: queue.Queue[bool] = queue.Queue()

    def _reader() -> None:
        while True:
            line = proc.stdout.readline()
            if not line:
                got.put(False)  # процесс умер, не сказав ready
                return
            try:
                if json.loads(line).get("event") == "ready":
                    got.put(True)
                    return
            except json.JSONDecodeError:
                continue  # мусор нативных библиотек в stdout

    threading.Thread(target=_reader, daemon=True).start()
    try:
        return got.get(timeout=READY_TIMEOUT_S)
    except queue.Empty:
        return False


def _worker_rss(proc: subprocess.Popen) -> int | None:
    """Память воркера в байтах (None — процесс умер или замер не удался)."""
    try:
        return psutil.Process(proc.pid).memory_info().rss
    except Exception:
        return None


def _wait_first_line(proc: subprocess.Popen) -> str | None:
    """Первая строка stdout после задания; None = воркер заморожен.

    Слушаем кусками по _POLL_SLICE_S, между ними меряем память: растёт —
    воркер честно грузит ML-стек, ждём дальше (медленный диск ≠
    заморозка). Не растёт NO_PROGRESS_TIMEOUT_S подряд — процесс стоит.
    """
    got: queue.Queue[str] = queue.Queue()
    threading.Thread(
        target=lambda: got.put(proc.stdout.readline()), daemon=True
    ).start()
    deadline = time.monotonic() + FIRST_EVENT_TIMEOUT_S
    last_rss = _worker_rss(proc)
    growing_at = time.monotonic()
    while True:
        try:
            return got.get(timeout=_POLL_SLICE_S)
        except queue.Empty:
            pass
        now = time.monotonic()
        if now > deadline:
            print(
                f"[parse] no event within {FIRST_EVENT_TIMEOUT_S:.0f}s after job",
                file=sys.stderr,
            )
            return None
        rss = _worker_rss(proc)
        if rss is not None and (last_rss is None or rss - last_rss >= _RSS_GROWTH_MIN):
            last_rss = rss
            growing_at = now
        elif now - growing_at > NO_PROGRESS_TIMEOUT_S:
            mb = (rss or 0) / 1_000_000
            print(
                f"[parse] worker memory static at {mb:.0f} MB for "
                f"{NO_PROGRESS_TIMEOUT_S:.0f}s, no events",
                file=sys.stderr,
            )
            return None


def _mark_blocked(reason: str) -> None:
    """Запомнить, что воркер заморожен, и объяснить это в app.log."""
    global _worker_blocked
    _worker_blocked = True
    print(
        f"[parse] {reason} — EDR/antivirus freeze? "
        "Falling back to in-process parse until restart",
        file=sys.stderr,
    )


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
            if not _wait_ready(_worker):
                _forget(_worker)
                raise _WorkerBlockedError
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

    Заморозка воркера EDR/антивирусом (инцидент 2026-08-10/11) ловится
    в двух точках: нет ready за READY_TIMEOUT_S после спавна, или нет
    ни одного события за FIRST_EVENT_TIMEOUT_S после отправки задания
    (заморозка на первом импорте docling/torch). В обоих случаях
    замёрзший процесс убивается, документ парсится в родителе, и до
    перезапуска приложения воркер больше не спавнится.
    """
    if not _worker_blocked:
        job = {
            "slug": slug,
            "pdf_path": pdf_path,
            "doc_dir": str(doc_dir),
            "pages_dir": str(pages_dir) if pages_dir else None,
        }
        with _lock:
            try:
                proc = _send_job(job)
            except _WorkerBlockedError:
                _mark_blocked("worker never became ready")
            else:
                got_first = False
                while True:
                    if got_first:
                        line = proc.stdout.readline()
                    else:
                        # До первого события воркер грузит ML-стек;
                        # причина отказа уже в логе от _wait_first_line.
                        line = _wait_first_line(proc)
                        if line is None:
                            _forget(proc)
                            _mark_blocked("worker frozen after job")
                            break  # → фоллбек ниже
                    if not line:
                        # EOF: воркер умер посреди задания (bad_alloc,
                        # segfault). Раньше это роняло ВСЁ приложение —
                        # теперь только документ.
                        _forget(proc)
                        raise ParseFailedError(msg("err.parse_crashed"))
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        # Нативная библиотека написала в stdout мимо
                        # редиректа воркера — не протокол, просто в лог.
                        print(f"[parse] {line.rstrip()}", file=sys.stderr)
                        continue
                    got_first = True
                    kind = event.get("event")
                    if kind == "text_pages" and on_text_pages:
                        on_text_pages(event["total"])
                    elif kind == "drawing_page" and on_drawing_page:
                        on_drawing_page(event["done"], event["total"])
                    elif kind == "done":
                        return
                    elif kind == "error":
                        raise ParseFailedError(
                            classify_by_name(event["type"], event["text"])
                        )
    _parse_in_process(
        slug, pdf_path, doc_dir, pages_dir, on_text_pages, on_drawing_page
    )


def _parse_in_process(
    slug: str,
    pdf_path: str | None,
    doc_dir: Path,
    pages_dir: Path | None,
    on_text_pages: Callable[[int], None] | None,
    on_drawing_page: Callable[[int, int], None] | None,
) -> None:
    """Запасной путь: parse в основном процессе, как до воркера.

    Индексация работает и там, где EDR/антивирус замораживает дочерний
    exe. Цена — модели остаются в памяти родителя до перезапуска.
    Ошибки пробрасываются сырыми: пайплайн классифицирует их сам, как в
    довокерные времена.
    """
    from pipeline import parse as parse_step

    parse_step.process(
        slug,
        pdf_path=pdf_path,
        doc_dir=doc_dir,
        document_id=slug,
        pages_dir=pages_dir,
        on_text_pages=on_text_pages,
        on_drawing_page=on_drawing_page,
    )


def stop_worker() -> None:
    """Убить воркера при выходе приложения — сирота держал бы гигабайты.

    Без _lock: выход из трея не должен ждать конца часового OCR.
    """
    proc = _worker
    if proc is not None and proc.poll() is None:
        proc.kill()
