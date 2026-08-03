"""Race of two machines in a shared network folder (simulated by two processes).

The red tests pin down two bugs:
- save_json_atomic: all writers shared one tmp file (`X.tmp`) — on parallel
  writes of the same file the rival "steals" the tmp from under os.replace;
- ensure_meta: unsafe "read — missing — create": two machines opening a new
  folder for the first time issue DIFFERENT folder_ids; the losing label
  orphans documents and causes repeated paid indexing.
"""

import multiprocessing as mp
from multiprocessing.queues import Queue
from multiprocessing.synchronize import Barrier
from pathlib import Path

from backend.core import index_store
from common.jsonio import save_json_atomic

# Enough rounds for the race to reproduce reliably,
# and few enough for the test to take seconds.
JSONIO_ROUNDS = 200
META_ROUNDS = 20
WAIT = 30  # seconds; a broken barrier instead of a test hung forever


def _hammer_save(target: str, barrier: Barrier, name: str, results: Queue) -> None:
    """Writes the same file in lockstep with the rival (a barrier every round)."""
    errors: list[str] = []
    for i in range(JSONIO_ROUNDS):
        try:
            barrier.wait(timeout=WAIT)
            save_json_atomic(Path(target), {"writer": name, "round": i})
        except Exception as exc:
            errors.append(f"round {i}: {type(exc).__name__}: {exc}")
    results.put(errors)


def _mint_meta(base: str, barrier: Barrier, results: Queue) -> None:
    """Calls ensure_meta on a fresh folder in lockstep with the rival."""
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
    # Atomic write invariant: parallel writes of one file from two
    # processes crash neither writer.
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
    # Folder passport invariant: no matter how many machines open a new
    # folder at once, they must all end up with ONE folder_id. Otherwise
    # documents indexed under the losing label become orphans.
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
