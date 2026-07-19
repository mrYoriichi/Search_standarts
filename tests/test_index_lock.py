"""Тесты lock-файла индексации папки."""

import json
import os
import threading
import time

from backend.core import index_lock, index_store


def _write_foreign_lock(library_path, owner: str, ts: float):
    """Кладёт чужой лок с заданным временем (симулируем другую машину)."""
    root = index_store.index_root(library_path)
    root.mkdir(parents=True, exist_ok=True)
    with open(root / index_lock.LOCK_FILENAME, "w", encoding="utf-8") as f:
        json.dump({"owner": owner, "ts": ts}, f)


def test_acquire_free_folder(tmp_path):
    assert index_lock.acquire(tmp_path) is None
    # Лок-файл реально создан и он наш.
    assert index_lock.holder(tmp_path) is None


def test_acquire_is_ours_again(tmp_path):
    index_lock.acquire(tmp_path)
    # Повторный acquire той же машиной — свободно (наш лок).
    assert index_lock.acquire(tmp_path) is None


def test_foreign_fresh_lock_blocks(tmp_path):
    _write_foreign_lock(tmp_path, "PC-KOLEGA", time.time())
    assert index_lock.holder(tmp_path) == "PC-KOLEGA"
    assert index_lock.acquire(tmp_path) == "PC-KOLEGA"


def test_stale_lock_can_be_taken(tmp_path):
    # Чужой лок старше TTL — считаем брошенным, перехватываем.
    _write_foreign_lock(tmp_path, "PC-KOLEGA", time.time() - index_lock.TTL_SECONDS - 1)
    assert index_lock.holder(tmp_path) is None
    assert index_lock.acquire(tmp_path) is None


def test_done_releases_after_last_doc(tmp_path):
    index_lock.acquire(tmp_path)
    index_lock.register(tmp_path, 2)
    index_lock.done(tmp_path)
    # Ещё один документ в работе — лок держим.
    assert (index_store.index_root(tmp_path) / index_lock.LOCK_FILENAME).exists()
    index_lock.done(tmp_path)
    # Последний закончил — лок снят.
    assert not (index_store.index_root(tmp_path) / index_lock.LOCK_FILENAME).exists()


def test_second_acquire_keeps_inflight_counter(tmp_path):
    # Повторный «Indexovat» во время работы папки не должен обнулять счётчик:
    # иначе done() старой партии снимал бы лок, пока новая ещё пишет.
    lock_file = index_store.index_root(tmp_path) / index_lock.LOCK_FILENAME
    index_lock.acquire(tmp_path)
    index_lock.register(tmp_path, 2)
    index_lock.acquire(tmp_path)  # вторая партия той же машины
    index_lock.register(tmp_path, 1)
    index_lock.done(tmp_path)
    index_lock.done(tmp_path)
    # Один документ ещё в работе — лок держим.
    assert lock_file.exists()
    index_lock.done(tmp_path)
    assert not lock_file.exists()


def test_unreadable_lock_counts_as_busy(tmp_path):
    # Сбой ЧТЕНИЯ (не «файла нет») — не повод перезаписывать чужой лок.
    # open() на папке с именем лок-файла даёт IsADirectoryError (подвид OSError).
    root = index_store.index_root(tmp_path)
    root.mkdir(parents=True)
    (root / index_lock.LOCK_FILENAME).mkdir()
    assert index_lock.holder(tmp_path) is not None
    assert index_lock.acquire(tmp_path) is not None


def test_concurrent_acquire_single_winner(tmp_path, monkeypatch):
    # Гонка №3 из аудита: несколько «машин» одновременно жмут «Indexovat»
    # на свободной папке — выиграть должна ровно одна. Раньше acquire был
    # «прочитал → записал» без атомарности, и выигрывали все сразу.
    monkeypatch.setattr(index_lock, "owner", lambda: threading.current_thread().name)

    for round_no in range(20):
        library = tmp_path / f"round{round_no}"
        library.mkdir()
        results: dict[str, str | None] = {}
        barrier = threading.Barrier(8)

        def worker(lib=library, res=results, bar=barrier):
            bar.wait()  # все 8 стартуют одновременно
            res[threading.current_thread().name] = index_lock.acquire(lib)

        threads = [
            threading.Thread(target=worker, name=f"r{round_no}-pc{i}") for i in range(8)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        winners = [name for name, res in results.items() if res is None]
        assert len(winners) == 1, f"раунд {round_no}: выиграли {winners}"


def test_fresh_broken_lock_counts_as_busy(tmp_path):
    # Свежий битый JSON может быть чужим локом, который прямо сейчас
    # дописывается (создание файла и запись JSON — два разных вызова).
    # Перехватить его — значит вернуть гонку из аудита (№3).
    root = index_store.index_root(tmp_path)
    root.mkdir(parents=True)
    (root / index_lock.LOCK_FILENAME).write_text("{oops", encoding="utf-8")
    assert index_lock.holder(tmp_path) is not None
    assert index_lock.acquire(tmp_path) is not None


def test_stale_broken_lock_is_free(tmp_path):
    # Протухший мусор (упали посреди записи и не вернулись) — перехватываем,
    # как обычный протухший лок: возраст берём из mtime файла.
    root = index_store.index_root(tmp_path)
    root.mkdir(parents=True)
    lock_file = root / index_lock.LOCK_FILENAME
    lock_file.write_text("{oops", encoding="utf-8")
    old = time.time() - index_lock.TTL_SECONDS - 1
    os.utime(lock_file, (old, old))
    assert index_lock.holder(tmp_path) is None
    assert index_lock.acquire(tmp_path) is None
