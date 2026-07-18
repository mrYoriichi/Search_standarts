"""Тесты lock-файла индексации папки."""

import json
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


def test_broken_lock_json_is_free(tmp_path):
    # Мусор в файле — такой лок можно перехватить (это не сетевой сбой).
    root = index_store.index_root(tmp_path)
    root.mkdir(parents=True)
    (root / index_lock.LOCK_FILENAME).write_text("{oops", encoding="utf-8")
    assert index_lock.holder(tmp_path) is None
    assert index_lock.acquire(tmp_path) is None
