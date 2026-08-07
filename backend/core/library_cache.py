"""In-memory library cache (chunks + embeddings).

Reading every document's chunks.json and embeddings.json on EVERY
question is expensive (hundreds of MB from disk at 200 documents).
Documents do not change between questions — so load once, keep in RAM.

When the library changes (a document processed / deleted / renamed /
re-indexed) invalidate() is called — the next get_library() re-reads
disk.

Loaded data is treated as read-only: search and filtering never mutate
it (filter_library builds new lists), so handing the same object to
different requests is safe.
"""

import os
import threading
import time
from pathlib import Path

import numpy as np

from search.library import EmptyLibraryError, load_library
from indexing.bm25_index import tokenize_chunk
from backend.core import index_store
from backend.core.paths import PROJECTS_DATA_DIR
from backend.core.ui_messages import msg


# The cache and its lock. FastAPI requests and the background pipeline
# run on different threads — the lock guards concurrent load/invalidate.
_lock = threading.Lock()
_cache: tuple[list[dict], dict] | None = None
# BM25 tokens by chunk_id. Computed once; every question builds BM25 from
# them instead of re-tokenizing the corpus. Reset together with _cache.
_tokens_cache: dict[str, list[str]] | None = None
# Fingerprint of the shared folders at cache-load time (_current_fingerprint).
_fingerprint: dict[str, int] | None = None
# Sweep throttle: on a network share 200 stats cost 0.2-10 s (SMB/VPN),
# and the sweep runs under _lock before EVERY question. Inside the TTL
# the fingerprint is not recomputed — a colleague's re-index is noticed
# up to a minute late (acceptable); local changes go through
# invalidate() and bypass the TTL.
_FINGERPRINT_TTL_S = 60.0
_last_sweep = 0.0  # time.monotonic() of the last sweep; 0 = never


def _shared_index_roots() -> list[Path]:
    """.search_index roots of every library AND archive folder
    (unreachable included).

    Indexes live next to the user's PDFs — in `<folder>/.search_index/`;
    since 2026-08-07 the project archive stores them the same way. Slugs
    carry the folder/project tag (`{tag}__…`), so chunks of different
    folders cannot collide in the merged pool. The same physical folder
    attached as both a library and an archive is loaded once (same_dir).
    Existence is NOT checked here: _load_merged skips missing roots
    itself, and the fingerprint needs unreachable roots too — to tell
    "the drive dropped" from "the documents were deleted".
    """
    from backend.core.database import SessionLocal
    from backend.modules.settings import service as settings_service

    db = SessionLocal()
    try:
        folder_paths = settings_service.get_library_paths(
            db
        ) + settings_service.get_projects_paths(db)
    finally:
        db.close()
    roots = []
    seen: list[Path] = []
    for folder_path in folder_paths:
        p = Path(folder_path)
        if any(index_store.same_dir(p, s) for s in seen):
            continue  # same physical folder under a second path — no doubling
        seen.append(p)
        roots.append(index_store.index_root(p))
    return roots


def _load_merged() -> tuple[list[dict], dict]:
    """Merge the pools into one (chunks, embeddings_index): the user's
    norms (library folders) and the project archive.

    All pools must share one embedding model — vectors from different
    models are incomparable. An empty/missing pool is silently skipped;
    it is only an error when no pool has any ready document.
    """
    roots = _shared_index_roots()
    if PROJECTS_DATA_DIR.exists():
        # Legacy archive pool: indexed by an old app version and not yet
        # migrated into the project folder (or the folder is read-only).
        roots.append(PROJECTS_DATA_DIR)

    all_chunks: list[dict] = []
    all_chunk_ids: list[str] = []
    matrices: list[np.ndarray] = []
    model: str | None = None
    for root in roots:
        if not root.exists():
            continue
        try:
            chunks, index = load_library(root)
        except EmptyLibraryError:
            continue  # no ready documents in this root — fine
        # Other RuntimeErrors (mixed models inside a root) propagate: the
        # router returns 400 with the text instead of silently dropping
        # the folder.
        if model is None:
            model = index["model"]
        elif model != index["model"]:
            # The text reaches the user in the UI (router detail).
            raise RuntimeError(
                msg("lib.mixed_models_pools", model_a=model, model_b=index["model"])
            )
        all_chunks.extend(chunks)
        all_chunk_ids.extend(index["chunk_ids"])
        matrices.append(index["matrix"])

    if not all_chunks:
        # The text reaches the user in the UI (router detail).
        raise RuntimeError(msg("lib.empty_library"))
    # Pool matrices are already normalized (build_matrix_index) — just
    # stack them. Row order matches all_chunk_ids.
    matrix = np.vstack(matrices)
    return all_chunks, {"model": model, "chunk_ids": all_chunk_ids, "matrix": matrix}


def _current_fingerprint(prev: dict[str, int] | None) -> dict[str, int]:
    """Fingerprint of the shared folders: mtime of each embeddings.json.

    Only shared roots (_shared_index_roots — library and archive
    folders): ANOTHER machine can rewrite them through the shared network
    folder, and our local invalidate() never sees it. The legacy local
    archive pool (projects_data) is mutated only by this process — it
    calls invalidate() itself. embeddings.json is the last pipeline file;
    its change means a completed re-index, and a new/removed document
    shows up as an appeared/vanished key.

    An UNREACHABLE root (network drive dropped, VPN) ≠ "documents
    deleted": its entries are carried over from the previous fingerprint
    prev — the warm cache keeps answering with the full corpus, and the
    comparison is honest once the drive returns.
    """
    fp: dict[str, int] = {}
    for root in _shared_index_roots():
        try:
            slug_dirs = list(root.iterdir())
        except OSError:
            if prev:
                prefix = str(root) + os.sep
                fp.update({k: v for k, v in prev.items() if k.startswith(prefix)})
            continue
        for d in slug_dirs:
            emb = d / "embeddings.json"
            try:
                fp[str(emb)] = emb.stat().st_mtime_ns
            except OSError:
                continue
    return fp


def _ensure_fresh_locked() -> None:
    """Under _lock: drop and reload the cache if the shared folders changed."""
    global _cache, _tokens_cache, _fingerprint, _last_sweep
    now = time.monotonic()
    if _cache is not None and now - _last_sweep < _FINGERPRINT_TTL_S:
        return  # recent sweep — serve the warm cache without stats
    fp = _current_fingerprint(_fingerprint)
    _last_sweep = now
    if _cache is not None and fp != _fingerprint:
        _cache = None
        _tokens_cache = None
    if _cache is None:
        # Take the fingerprint BEFORE loading: a write racing the read
        # produces a mismatch and an honest reload on the next question.
        _fingerprint = fp
        _cache = _load_merged()


def get_library() -> tuple[list[dict], dict]:
    """Return (chunks, embeddings_index); reads disk on first use."""
    with _lock:
        _ensure_fresh_locked()
        return _cache


def get_library_with_tokens() -> tuple[list[dict], dict, dict[str, list[str]]]:
    """Return (chunks, embeddings_index, {chunk_id: BM25 tokens}) AT ONCE.

    Everything is taken under one lock — chunks and tokens are guaranteed
    to be of the same cache generation. Separate get_library() +
    "get_tokens()" calls used to race: invalidate() between them paired
    new-generation tokens with old chunks → KeyError on a question.
    Tokens are computed once; each question builds BM25 from them
    (build_bm25_from_tokens) without re-tokenizing the corpus.
    """
    global _tokens_cache
    with _lock:
        _ensure_fresh_locked()
        if _tokens_cache is None:
            _tokens_cache = {c["chunk_id"]: tokenize_chunk(c) for c in _cache[0]}
        return _cache[0], _cache[1], _tokens_cache


def invalidate() -> None:
    """Drop the caches — the next get_library()/get_tokens() re-reads disk."""
    global _cache, _tokens_cache, _fingerprint, _last_sweep
    with _lock:
        _cache = None
        _tokens_cache = None
        _fingerprint = None
        _last_sweep = 0.0
