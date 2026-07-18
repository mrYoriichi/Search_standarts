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
# Heartbeat освежает локи втрое чаще TTL — запас на пару пропущенных тиков.
HEARTBEAT_SECONDS = 5 * 60

# Счётчик документов «в работе» по папкам: последний закончивший снимает лок.
# Живёт в памяти (как progress); при падении лок снимет TTL, не счётчик.
_inflight_lock = threading.Lock()
_inflight: dict[str, int] = {}
_heartbeat_started = False


def owner() -> str:
    """Кто держит лок — имя машины (узнаваемо для коллег в сообщении)."""
    return socket.gethostname() or "neznámý"


def _lock_path(library_path: Path) -> Path:
    return index_store.index_root(library_path) / LOCK_FILENAME


def read_lock(library_path: Path) -> dict | None:
    """Содержимое лок-файла; None — файла нет или в нём мусор (битый JSON).

    Сбой ЧТЕНИЯ (сеть моргнула, нет прав) — это НЕ «свободно»: OSError уходит
    выше, и holder() считает папку занятой. Иначе сетевой сбой перезаписывал
    бы живой чужой лок, и две машины индексировали бы папку параллельно.
    """
    try:
        with open(_lock_path(library_path), encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except json.JSONDecodeError:
        return None  # мусор в файле — такой лок можно перехватывать


def _is_stale(lock: dict) -> bool:
    return (time.time() - lock.get("ts", 0)) > TTL_SECONDS


def holder(library_path: Path) -> str | None:
    """Кто СЕЙЧАС держит свежий чужой лок, иначе None (свободно/наш/протух)."""
    try:
        lock = read_lock(library_path)
    except OSError:
        # Лок не читается (сеть/права) — безопаснее считать папку занятой.
        return "neznámý počítač (zámek nelze přečíst)"
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
        # setdefault, НЕ сброс: повторный «Indexovat» во время работы папки
        # не должен обнулять счётчик — иначе первый же done() старой партии
        # снял бы лок, пока остальные документы ещё пишут в .search_index.
        _inflight.setdefault(str(library_path), 0)
    return None


def register(library_path: Path, n: int) -> None:
    """Сколько документов папки уходит в обработку (для снятия лока в конце)."""
    with _inflight_lock:
        _inflight[str(library_path)] = _inflight.get(str(library_path), 0) + n
    _ensure_heartbeat()


def refresh(library_path: Path) -> None:
    """Освежает ts нашего лока — heartbeat."""
    try:
        lock = read_lock(library_path)
    except OSError:
        return  # сеть моргнула — попробуем в следующий heartbeat
    if lock and lock.get("owner") == owner():
        _write(library_path)


def _heartbeat_loop() -> None:
    while True:
        time.sleep(HEARTBEAT_SECONDS)
        with _inflight_lock:
            busy = [Path(p) for p, n in _inflight.items() if n > 0]
        for library_path in busy:
            refresh(library_path)


def _ensure_heartbeat() -> None:
    """Ленивый старт daemon-потока, освежающего локи занятых папок.

    refresh только в начале документа мало: документы могут часами ждать
    очереди executor'а (3 потока), а один документ — обрабатываться дольше
    TTL. Без heartbeat лок протухал, и другая машина заходила в папку
    параллельно. Поток daemon: умирает вместе с процессом; после падения
    лок честно снимет TTL.
    """
    global _heartbeat_started
    with _inflight_lock:
        if _heartbeat_started:
            return
        _heartbeat_started = True
    threading.Thread(
        target=_heartbeat_loop, name="index-lock-heartbeat", daemon=True
    ).start()


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
        try:
            lock = read_lock(library_path)
        except OSError:
            return  # лок не читается — его снимет TTL
        if lock and lock.get("owner") == owner():
            try:
                _lock_path(library_path).unlink()
            except OSError:
                pass
