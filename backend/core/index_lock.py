"""Lock-файл индексации папки: не даёт двум машинам индексировать общую
сетевую папку одновременно (задвоенные траты на vision + гонки записи в
`.search_index`).

Лок — файл `<папка>/.search_index/index.lock` с `{owner, ts}`. Пока идёт
индексация, `ts` освежается (heartbeat); по завершении последнего документа
папки лок снимается. Если приложение упало или потеряло сеть, лок протухнет
(TTL) и другая машина сможет его перехватить — папка не залипнет навсегда.

Координация нужна между РАЗНЫМИ машинами на общей папке. Внутри одного
приложения двойной запуск и так не проходит (двухшаговый скан + статус
processing), поэтому тут — только межмашинная страховка.
"""

import json
import socket
import threading
import time
from pathlib import Path

from backend.core import index_store

LOCK_FILENAME = "index.lock"
# Лок старше этого времени считаем брошенным (машина упала/ушла из сети).
TTL_SECONDS = 15 * 60

# Счётчик документов «в работе» по папкам: последний закончивший снимает лок.
# Живёт в памяти (как progress); при падении лок снимет TTL, не счётчик.
_inflight_lock = threading.Lock()
_inflight: dict[str, int] = {}


def owner() -> str:
    """Кто держит лок — имя машины (узнаваемо для коллег в сообщении)."""
    return socket.gethostname() or "neznámý"


def _lock_path(library_path: Path) -> Path:
    return index_store.index_root(library_path) / LOCK_FILENAME


def read_lock(library_path: Path) -> dict | None:
    """Содержимое лок-файла или None (нет файла / битый / нечитаем)."""
    try:
        with open(_lock_path(library_path), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _is_stale(lock: dict) -> bool:
    return (time.time() - lock.get("ts", 0)) > TTL_SECONDS


def holder(library_path: Path) -> str | None:
    """Кто СЕЙЧАС держит свежий чужой лок, иначе None (свободно/наш/протух)."""
    lock = read_lock(library_path)
    if lock is None or _is_stale(lock):
        return None
    who = lock.get("owner")
    return None if who == owner() else who


def _write(library_path: Path) -> None:
    root = index_store.index_root(library_path)
    try:
        root.mkdir(parents=True, exist_ok=True)
        with open(_lock_path(library_path), "w", encoding="utf-8") as f:
            json.dump({"owner": owner(), "ts": time.time()}, f)
    except OSError:
        pass  # read-only папка — координировать нечем, индексация там всё равно упадёт


def acquire(library_path: Path) -> str | None:
    """Пытается занять лок папки.

    None — заняли (было свободно / протухло / уже наш). Иначе — имя машины,
    которая держит свежий лок: индексацию этой папки НЕ начинаем.
    """
    who = holder(library_path)
    if who is not None:
        return who
    _write(library_path)
    with _inflight_lock:
        _inflight[str(library_path)] = 0
    return None


def register(library_path: Path, n: int) -> None:
    """Сколько документов папки уходит в обработку (для снятия лока в конце)."""
    with _inflight_lock:
        _inflight[str(library_path)] = _inflight.get(str(library_path), 0) + n


def refresh(library_path: Path) -> None:
    """Освежает ts нашего лока — heartbeat в начале обработки каждого документа."""
    lock = read_lock(library_path)
    if lock and lock.get("owner") == owner():
        _write(library_path)


def done(library_path: Path) -> None:
    """Документ папки закончил обработку. Последний — снимает лок."""
    key = str(library_path)
    with _inflight_lock:
        left = _inflight.get(key, 1) - 1
        if left <= 0:
            _inflight.pop(key, None)
        else:
            _inflight[key] = left
        release = left <= 0
    if release:
        lock = read_lock(library_path)
        if lock and lock.get("owner") == owner():
            try:
                _lock_path(library_path).unlink()
            except OSError:
                pass
