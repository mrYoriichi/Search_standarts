"""Воркер parse: дочерний процесс, который умирает после очереди.

Зачем: docling/torch/OCR занимают гигабайты, а Python не возвращает ОС
память загруженных моделей до смерти процесса — с треем приложение
живёт неделями, и после первой индексации 3–4 ГБ висели бы постоянно.
Поэтому CPU-тяжёлая стадия parse выполняется здесь: модели грузятся
один раз на очередь, при тишине IDLE_TIMEOUT_S процесс выходит сам,
и ОС забирает память.

Протокол — JSON-строки (ASCII, кодировка пайпа не важна):
  stdin  ← задание {"slug", "pdf_path", "doc_dir", "pages_dir"}
  stdout → {"event": "text_pages"|"drawing_page"|"done"|"error", ...}
Ошибка задания не убивает воркер — следующее задание обрабатывается.
Классификация текста ошибки — дело родителя: язык UI живёт в его
процессе, воркер шлёт сырые тип и текст исключения.
"""

import json
import queue
import sys
import threading
import traceback
from pathlib import Path
from typing import TextIO

IDLE_TIMEOUT_S = 60.0


class _SafeWriter:
    """stderr воркера, переживающий смерть родителя.

    Родителя убили через диспетчер задач → каналы закрыты, запись
    кидает OSError (WinError/Errno 22). Печать пайплайна (Reading…,
    трейсбеки) не должна ронять сироту с системным окном «Unhandled
    exception» (инцидент 2026-08-10) — глотаем и пишем в никуда;
    процесс завершит первый же _emit в протокол.
    """

    def __init__(self, target: TextIO) -> None:
        self._target = target

    def write(self, text: str) -> int:
        try:
            return self._target.write(text)
        except OSError:
            return len(text)

    def flush(self) -> None:
        try:
            self._target.flush()
        except OSError:
            pass


def _emit(out: TextIO, payload: dict) -> None:
    try:
        out.write(json.dumps(payload) + "\n")
        out.flush()
    except OSError:
        # Родитель умер (труба закрыта) — события слать некому и
        # работать не для кого. Тихий выход вместо системного окна.
        raise SystemExit(0) from None


def _handle_job(job: dict, out: TextIO) -> None:
    print(f"job received: {job.get('slug')}", file=sys.stderr)
    # Ленивый импорт: docling/torch грузятся при первом задании,
    # сам старт воркера мгновенный.
    from pipeline import parse as parser_step

    pages_dir = job.get("pages_dir")
    try:
        parser_step.process(
            job["slug"],
            pdf_path=job["pdf_path"],
            doc_dir=Path(job["doc_dir"]),
            # document_id = slug: артефакты несут scoped-slug из БД,
            # иначе фильтр «Kde hledat» не найдёт ни одного чанка.
            document_id=job["slug"],
            # None (архив) — parse сам положит скриншоты в doc_dir/pages.
            pages_dir=Path(pages_dir) if pages_dir else None,
            on_text_pages=lambda total: _emit(
                out, {"event": "text_pages", "total": total}
            ),
            on_drawing_page=lambda done, total: _emit(
                out, {"event": "drawing_page", "done": done, "total": total}
            ),
        )
    except Exception as exc:  # noqa: BLE001 — любой сбой уходит родителю
        traceback.print_exc()  # полный трейсбек — в stderr → app.log родителя
        _emit(out, {"event": "error", "type": type(exc).__name__, "text": str(exc)})
    else:
        _emit(out, {"event": "done"})


def serve(inp: TextIO, out: TextIO, idle_timeout: float = IDLE_TIMEOUT_S) -> None:
    """Цикл заданий: строка из inp → задание; тишина idle_timeout → выход.

    stdin читает отдельный поток: у пайпов нет кроссплатформенного
    «readline с таймаутом», а очередь его даёт. Поток daemon — при
    выходе из serve он не держит процесс.
    """
    lines: queue.Queue[str | None] = queue.Queue()

    def _reader() -> None:
        for line in inp:
            lines.put(line)
        lines.put(None)  # EOF: родитель закрыл stdin — работы больше не будет

    threading.Thread(target=_reader, daemon=True).start()
    # Рукопожатие: родитель не шлёт задания, пока не увидит ready.
    # Замороженный EDR/антивирусом процесс (инцидент 2026-08-10) так
    # отличим от здорового — родитель дождётся таймаута и уйдёт в
    # фоллбек вместо вечного ожидания.
    _emit(out, {"event": "ready"})
    # Маркер в app.log родителя (через префикс [parse]): видно, что
    # процесс воркера дожил до Python-кода и его stderr доходит.
    print("worker ready", file=sys.stderr)
    while True:
        try:
            line = lines.get(timeout=idle_timeout)
        except queue.Empty:
            return  # очередь пуста — умираем и возвращаем ОС память моделей
        if line is None:
            return
        if not line.strip():
            continue
        _handle_job(json.loads(line), out)


def main() -> None:
    proto_out = sys.stdout
    # Печать пайплайна и библиотек (Reading..., прогресс-бары docling)
    # не должна ломать протокол — весь обычный вывод уводим в stderr,
    # родитель дописывает его в app.log. Обёртка _SafeWriter — чтобы
    # сирота (родителя убили) не падал на печати в мёртвый канал.
    safe_err = _SafeWriter(sys.stderr)
    sys.stdout = safe_err
    sys.stderr = safe_err
    serve(sys.stdin, proto_out)


if __name__ == "__main__":
    main()
