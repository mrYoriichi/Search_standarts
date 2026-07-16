"""Прогресс фоновой обработки документов — для отображения в UI.

Эфемерное состояние в памяти процесса: {slug: "popis obrázků: strana 12/47"}.
В БД сознательно не пишем: прогресс живёт, пока живёт пайплайн; после
рестарта обработка возобновляется и прогресс появится снова.

Пайплайны пишут из потоков ThreadPoolExecutor, API читает из своих — поэтому lock.
"""

import threading

_lock = threading.Lock()
_progress: dict[str, str] = {}


def set_progress(slug: str, text: str) -> None:
    with _lock:
        _progress[slug] = text


def get_progress(slug: str) -> str | None:
    with _lock:
        return _progress.get(slug)


def clear_progress(slug: str) -> None:
    with _lock:
        _progress.pop(slug, None)
