"""Folder indexing lock file: stops two machines from indexing one
shared network folder at once (doubled vision spending + write races in
`.search_index`).

The lock is the file `<folder>/.search_index/index.lock` with
`{owner, ts}`. While indexing runs, `ts` is refreshed (heartbeat); when
the folder's last document finishes, the lock is removed. If the app
crashed or lost the network, the lock goes stale (TTL) and another
machine may take it over — the folder never sticks forever.

Coordination is needed between DIFFERENT machines on a shared folder.
Inside one app a double start is already impossible (two-step scan +
processing status), so this is inter-machine insurance only.
"""

import json
import os
import socket
import threading
import time
from pathlib import Path

from backend.core import index_store

LOCK_FILENAME = "index.lock"
# A lock older than this is considered abandoned (machine crashed/offline).
TTL_SECONDS = 15 * 60
# The heartbeat refreshes locks three times per TTL — margin for a couple
# of missed ticks.
HEARTBEAT_SECONDS = 5 * 60

# In-flight document counter per folder: the last one to finish releases
# the lock. Lives in memory (like progress); after a crash the TTL, not
# the counter, releases the lock.
_inflight_lock = threading.Lock()
_inflight: dict[str, int] = {}
_heartbeat_started = False


def owner() -> str:
    """Who holds the lock — the machine name (recognizable to colleagues)."""
    return socket.gethostname() or "neznámý"


def _lock_path(library_path: Path) -> Path:
    return index_store.index_root(library_path) / LOCK_FILENAME


def read_lock(library_path: Path) -> dict | None:
    """Lock file contents; None — no file.

    A READ failure (network blip, no permission) is NOT "free": the
    OSError propagates and holder() treats the folder as busy. Otherwise
    a network hiccup would overwrite a live foreign lock and two machines
    would index in parallel.

    Garbage in the file (broken/partially written JSON) — the owner is
    unknown, so the age comes from the file mtime: {owner: None,
    ts: mtime}. Fresh garbage may be a foreign lock being written RIGHT
    NOW (creating the file and writing JSON are two separate syscalls) —
    it must not be taken over; stale-by-TTL garbage may be, as before.
    """
    try:
        with open(_lock_path(library_path), encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except json.JSONDecodeError:
        try:
            return {"owner": None, "ts": _lock_path(library_path).stat().st_mtime}
        except OSError:
            return None  # vanished between read and stat — free


def _is_stale(lock: dict) -> bool:
    return (time.time() - lock.get("ts", 0)) > TTL_SECONDS


def holder(library_path: Path) -> str | None:
    """Who holds a fresh foreign lock NOW; None = free/ours/stale."""
    try:
        lock = read_lock(library_path)
    except OSError:
        # Unreadable lock (network/permissions) — safer to treat as busy.
        return "neznámý počítač (zámek nelze přečíst)"
    if lock is None or _is_stale(lock):
        return None
    who = lock.get("owner")
    if who is None:
        # A fresh half-written lock: owner not visible yet, folder busy.
        return "neznámý počítač (zámek se právě zapisuje)"
    return None if who == owner() else who


def _write(library_path: Path) -> None:
    root = index_store.index_root(library_path)
    try:
        root.mkdir(parents=True, exist_ok=True)
        with open(_lock_path(library_path), "w", encoding="utf-8") as f:
            json.dump({"owner": owner(), "ts": time.time()}, f)
    except OSError:
        pass  # read-only folder — nothing to coordinate with; indexing
        # there will fail with a clear error anyway


def _mark_inflight(library_path: Path) -> None:
    with _inflight_lock:
        # setdefault, NOT reset: a repeated "Index" click while the folder
        # is working must not zero the counter — the first done() of the
        # old batch would drop the lock while other documents still write
        # into .search_index.
        _inflight.setdefault(str(library_path), 0)


def _try_create(library_path: Path) -> bool:
    """Atomically create the lock file: O_EXCL — create ONLY if absent.

    The filesystem guarantees exactly one winner among concurrent
    attempts — no more "read → decide → write" window. True — the lock is
    ours. False — the file already exists (someone was faster). Other
    OSErrors (read-only folder) behave like _write: nothing to
    coordinate with, we work unlocked and indexing there fails clearly.
    """
    try:
        index_store.index_root(library_path).mkdir(parents=True, exist_ok=True)
        fd = os.open(_lock_path(library_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    except OSError:
        return True
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"owner": owner(), "ts": time.time()}, f)
    except OSError:
        pass  # network blip after creation — the empty lock reads as garbage
    return True


def acquire(library_path: Path) -> str | None:
    """Try to take the folder lock.

    None — taken (was free / stale / already ours). Otherwise the name of
    the machine holding a fresh lock: do NOT start indexing this folder.
    """
    if _try_create(library_path):
        _mark_inflight(library_path)
        return None

    # The file already exists. A fresh foreign lock — folder busy.
    who = holder(library_path)
    if who is not None:
        return who

    try:
        lock = read_lock(library_path)
    except OSError:
        return "neznámý počítač (zámek nelze přečíst)"
    if lock is not None and lock.get("owner") == owner() and not _is_stale(lock):
        _write(library_path)  # our live lock — just refresh ts
        _mark_inflight(library_path)
        return None

    # Stale/garbage/just-vanished lock: remove it and try to create
    # exactly once more — O_EXCL decides which machine wins. A tiny
    # window remains (both removed the stale lock simultaneously), but
    # that is a sub-second race on a rare path instead of a race on
    # every acquisition.
    try:
        _lock_path(library_path).unlink()
    except FileNotFoundError:
        pass
    except OSError:
        return "neznámý počítač (zámek nelze smazat)"
    if _try_create(library_path):
        _mark_inflight(library_path)
        return None
    return holder(library_path) or "jiný počítač"


def register(library_path: Path, n: int) -> None:
    """How many folder documents enter processing (for the final release)."""
    with _inflight_lock:
        _inflight[str(library_path)] = _inflight.get(str(library_path), 0) + n
    _ensure_heartbeat()


def refresh(library_path: Path) -> None:
    """Refresh our lock's ts — the heartbeat."""
    try:
        lock = read_lock(library_path)
    except OSError:
        return  # network blip — retried on the next heartbeat
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
    """Lazily start the daemon thread refreshing locks of busy folders.

    Refreshing only at document start is not enough: documents can wait
    hours in the executor queue (3 threads), and one document can process
    longer than the TTL. Without the heartbeat the lock went stale and
    another machine entered the folder in parallel. The thread is a
    daemon: it dies with the process; after a crash the TTL honestly
    releases the lock.
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
    """A folder document finished processing. The last one drops the lock."""
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
            return  # unreadable lock — the TTL will release it
        if lock and lock.get("owner") == owner():
            try:
                _lock_path(library_path).unlink()
            except OSError:
                pass
