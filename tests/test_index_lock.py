"""Tests of the folder indexing lock file."""

import json
import os
import threading
import time

from backend.core import index_lock, index_store


def _write_foreign_lock(library_path, owner: str, ts: float):
    """Plants a foreign lock with a given time (simulating another machine)."""
    root = index_store.index_root(library_path)
    root.mkdir(parents=True, exist_ok=True)
    with open(root / index_lock.LOCK_FILENAME, "w", encoding="utf-8") as f:
        json.dump({"owner": owner, "ts": ts}, f)


def test_acquire_free_folder(tmp_path):
    assert index_lock.acquire(tmp_path) is None
    # The lock file is actually created and is ours.
    assert index_lock.holder(tmp_path) is None


def test_acquire_is_ours_again(tmp_path):
    index_lock.acquire(tmp_path)
    # Repeated acquire by the same machine — free (our lock).
    assert index_lock.acquire(tmp_path) is None


def test_foreign_fresh_lock_blocks(tmp_path):
    _write_foreign_lock(tmp_path, "PC-KOLEGA", time.time())
    assert index_lock.holder(tmp_path) == "PC-KOLEGA"
    assert index_lock.acquire(tmp_path) == "PC-KOLEGA"


def test_stale_lock_can_be_taken(tmp_path):
    # A foreign lock older than TTL counts as abandoned — take it over.
    _write_foreign_lock(tmp_path, "PC-KOLEGA", time.time() - index_lock.TTL_SECONDS - 1)
    assert index_lock.holder(tmp_path) is None
    assert index_lock.acquire(tmp_path) is None


def test_done_releases_after_last_doc(tmp_path):
    index_lock.acquire(tmp_path)
    index_lock.register(tmp_path, 2)
    index_lock.done(tmp_path)
    # One more document in progress — keep the lock.
    assert (index_store.index_root(tmp_path) / index_lock.LOCK_FILENAME).exists()
    index_lock.done(tmp_path)
    # The last one finished — the lock is released.
    assert not (index_store.index_root(tmp_path) / index_lock.LOCK_FILENAME).exists()


def test_second_acquire_keeps_inflight_counter(tmp_path):
    # A repeated "Indexovat" while the folder works must not reset the
    # counter: else the old batch's done() would release the lock while the
    # new one is still writing.
    lock_file = index_store.index_root(tmp_path) / index_lock.LOCK_FILENAME
    index_lock.acquire(tmp_path)
    index_lock.register(tmp_path, 2)
    index_lock.acquire(tmp_path)  # a second batch from the same machine
    index_lock.register(tmp_path, 1)
    index_lock.done(tmp_path)
    index_lock.done(tmp_path)
    # One document still in progress — keep the lock.
    assert lock_file.exists()
    index_lock.done(tmp_path)
    assert not lock_file.exists()


def test_unreadable_lock_counts_as_busy(tmp_path):
    # A READ failure (not "file missing") is no reason to overwrite a foreign
    # lock. open() on a directory named like the lock file raises
    # IsADirectoryError (an OSError subtype).
    root = index_store.index_root(tmp_path)
    root.mkdir(parents=True)
    (root / index_lock.LOCK_FILENAME).mkdir()
    assert index_lock.holder(tmp_path) is not None
    assert index_lock.acquire(tmp_path) is not None


def test_concurrent_acquire_single_winner(tmp_path, monkeypatch):
    # Race #3 from the audit: several "machines" hit "Indexovat" on a free
    # folder at once — exactly one must win. acquire used to be a non-atomic
    # "read -> write", and everybody won at once.
    monkeypatch.setattr(index_lock, "owner", lambda: threading.current_thread().name)

    for round_no in range(20):
        library = tmp_path / f"round{round_no}"
        library.mkdir()
        results: dict[str, str | None] = {}
        barrier = threading.Barrier(8)

        def worker(lib=library, res=results, bar=barrier):
            bar.wait()  # all 8 start simultaneously
            res[threading.current_thread().name] = index_lock.acquire(lib)

        threads = [
            threading.Thread(target=worker, name=f"r{round_no}-pc{i}") for i in range(8)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        winners = [name for name, res in results.items() if res is None]
        assert len(winners) == 1, f"round {round_no}: winners {winners}"


def test_fresh_broken_lock_counts_as_busy(tmp_path):
    # Fresh broken JSON may be a foreign lock being written right now
    # (creating the file and writing JSON are two separate calls).
    # Taking it over would bring back audit race #3.
    root = index_store.index_root(tmp_path)
    root.mkdir(parents=True)
    (root / index_lock.LOCK_FILENAME).write_text("{oops", encoding="utf-8")
    assert index_lock.holder(tmp_path) is not None
    assert index_lock.acquire(tmp_path) is not None


def test_stale_broken_lock_is_free(tmp_path):
    # Stale garbage (crashed mid-write and never came back) — take over as
    # a normal stale lock: age comes from the file's mtime.
    root = index_store.index_root(tmp_path)
    root.mkdir(parents=True)
    lock_file = root / index_lock.LOCK_FILENAME
    lock_file.write_text("{oops", encoding="utf-8")
    old = time.time() - index_lock.TTL_SECONDS - 1
    os.utime(lock_file, (old, old))
    assert index_lock.holder(tmp_path) is None
    assert index_lock.acquire(tmp_path) is None
