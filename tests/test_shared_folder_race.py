"""Гонка двух машин в общей сетевой папке (имитация двумя процессами).

Красные тесты фиксируют два бага:
- save_json_atomic: у всех писателей один tmp-файл (`X.tmp`) — при
  параллельной записи одного файла соперник «уводит» tmp из-под os.replace;
- ensure_meta: небезопасный «прочитал — нет — создал»: две машины, впервые
  открывшие одну папку, выдают ей РАЗНЫЕ folder_id; проигравшая метка
  осиротит документы и вызовет повторную платную индексацию.
"""

import multiprocessing as mp
from multiprocessing.queues import Queue
from multiprocessing.synchronize import Barrier
from pathlib import Path

from backend.core import index_store
from jsonio import save_json_atomic

# Раундов достаточно, чтобы гонка воспроизводилась стабильно,
# и мало настолько, чтобы тест шёл секунды.
JSONIO_ROUNDS = 200
META_ROUNDS = 20
WAIT = 30  # сек; сломанный барьер вместо зависшего навсегда теста


def _hammer_save(target: str, barrier: Barrier, name: str, results: Queue) -> None:
    """Пишет один и тот же файл в такт с соперником (барьер каждый раунд)."""
    errors: list[str] = []
    for i in range(JSONIO_ROUNDS):
        try:
            barrier.wait(timeout=WAIT)
            save_json_atomic(Path(target), {"writer": name, "round": i})
        except Exception as exc:
            errors.append(f"round {i}: {type(exc).__name__}: {exc}")
    results.put(errors)


def _mint_meta(base: str, barrier: Barrier, results: Queue) -> None:
    """Вызывает ensure_meta на свежей папке в такт с соперником."""
    ids: list[str] = []
    for i in range(META_ROUNDS):
        try:
            barrier.wait(timeout=WAIT)
            meta = index_store.ensure_meta(Path(base) / f"round_{i}", "model-x")
            ids.append(meta["folder_id"])
        except Exception as exc:
            ids.append(f"ERROR round {i}: {type(exc).__name__}: {exc}")
    results.put(ids)


def test_parallel_writers_do_not_crash_each_other(tmp_path):
    # Инвариант атомарной записи: параллельная запись одного файла из двух
    # процессов не роняет ни одного из писателей.
    ctx = mp.get_context("spawn")
    barrier = ctx.Barrier(2)
    results = ctx.Queue()
    target = str(tmp_path / "meta.json")
    procs = [
        ctx.Process(target=_hammer_save, args=(target, barrier, name, results))
        for name in ("a", "b")
    ]
    for p in procs:
        p.start()
    errors = results.get(timeout=60) + results.get(timeout=60)
    for p in procs:
        p.join(timeout=60)
    assert errors == []


def test_two_machines_agree_on_folder_id(tmp_path):
    # Инвариант паспорта папки: сколько бы машин ни открыло новую папку
    # одновременно, folder_id у всех должен получиться ОДИН. Иначе документы,
    # проиндексированные под проигравшей меткой, осиротеют.
    ctx = mp.get_context("spawn")
    for i in range(META_ROUNDS):
        (tmp_path / f"round_{i}").mkdir()
    barrier = ctx.Barrier(2)
    results = ctx.Queue()
    procs = [
        ctx.Process(target=_mint_meta, args=(str(tmp_path), barrier, results))
        for _ in range(2)
    ]
    for p in procs:
        p.start()
    ids_a = results.get(timeout=60)
    ids_b = results.get(timeout=60)
    for p in procs:
        p.join(timeout=60)
    errors = [x for x in ids_a + ids_b if x.startswith("ERROR")]
    assert errors == []
    assert ids_a == ids_b
