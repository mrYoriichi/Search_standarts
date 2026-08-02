"""Indexes inside the library folder: <folder>/.search_index/{slug}/.

The public version's source of truth is the PDF folder itself: index
artifacts live next to the documents in the hidden .search_index
subfolder, the DB is only a local status cache. One user indexes a
network folder — everyone else attaches it and searches at no cost
("adoption" of ready indexes at scan time).

meta.json is the folder passport: embedding model, format version, a
permanent folder id. The id is identical on every machine regardless of
the mount path — it prefixes chunk ids so multiple folders coexist.

User files are never touched (decision #16): writes go ONLY inside
.search_index/.
"""

import json
import os
import time
import uuid
from pathlib import Path

from common.jsonio import save_json_atomic

INDEX_DIR_NAME = ".search_index"
META_FILENAME = "meta.json"
# Bump on an incompatible artifact-format change — old indexes stop being
# adopted and get re-indexed.
FORMAT_VERSION = 1


def index_root(library_path: Path) -> Path:
    """Index root of a library folder."""
    return library_path / INDEX_DIR_NAME


def same_dir(a: Path, b: Path) -> bool:
    """Same directory on disk (symlink / second mount)?

    One physical folder attached under two paths must not count as two:
    the scan would register files twice, the cache would double chunks,
    and the folder_id would be re-issued ping-pong on every request.
    """
    try:
        return a.samefile(b)
    except OSError:
        return False


def doc_dir(library_path: Path, slug: str) -> Path:
    """Artifact folder of one document."""
    return index_root(library_path) / slug


def read_meta(library_path: Path) -> dict | None:
    """Read the folder's meta.json. Missing file or broken JSON — None."""
    meta_path = index_root(library_path) / META_FILENAME
    try:
        with open(meta_path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def ensure_meta(library_path: Path, embedding_model: str) -> dict:
    """Return the folder's meta.json, creating it on first use.

    An existing meta is NOT overwritten (the id and model are permanent
    folder properties; a model conflict is caught by the caller).

    Creation is exclusive (O_EXCL, like the lock file): when two machines
    open a shared folder for the first time simultaneously, exactly one
    writes the passport and the other reads the winner's — otherwise the
    folder would get two folder_ids and the loser's documents would be
    orphaned.
    """
    meta = read_meta(library_path)
    if meta is not None:
        return meta
    meta = {
        "format_version": FORMAT_VERSION,
        "folder_id": uuid.uuid4().hex,
        "embedding_model": embedding_model,
    }
    if not library_path.is_dir():
        # The library folder is NOT created here (decision #16): its
        # absence means a path typo or a dropped network drive — masking
        # that is wrong.
        raise FileNotFoundError(f"Library folder unavailable: {library_path}")
    root = index_root(library_path)
    root.mkdir(exist_ok=True)
    try:
        fd = os.open(root / META_FILENAME, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return _wait_meta(library_path)  # lost the race — read the winner's
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    return meta


def _wait_meta(library_path: Path, attempts: int = 50, delay: float = 0.1) -> dict:
    """Read meta.json with retries: the race winner may still be writing.

    No valid JSON after the retries means it is not a race but a broken
    file. Silently re-issuing the id is forbidden (orphaned documents,
    paid re-indexing of the whole folder) — so a loud error.
    """
    for _ in range(attempts):
        meta = read_meta(library_path)
        if meta is not None:
            return meta
        time.sleep(delay)
    raise OSError(
        "Broken folder passport (invalid JSON): "
        f"{index_root(library_path) / META_FILENAME}"
    )


def scoped_slug(folder_id: str, filename_slug: str) -> str:
    """Document id = folder tag + file-name slug (`{folder_id}__{file}`).

    The same file in different folders gets different ids (same trick as
    the project archive: `{project}__{file}`). folder_id is the permanent
    folder tag from meta.json, identical on all machines, so the id does
    not depend on where the folder is mounted.
    """
    return f"{folder_id}__{filename_slug}"


def folder_id_of(slug: str) -> str | None:
    """Folder tag from a document id. No `__` separator — None
    (untagged slug from a build before scoped slugs)."""
    folder_id, sep, _ = slug.partition("__")
    return folder_id if sep else None


def resolve_folder(paths: list[Path], slug: str) -> Path | None:
    """Find which folder in the list owns the document (by the slug tag).

    slug = `{folder_id}__{file}`; folder_id is checked against each
    folder's meta.json. None — the folder is detached or the slug is
    legacy (untagged).
    """
    fid = folder_id_of(slug)
    if fid is None:
        return None
    for lib in paths:
        meta = read_meta(lib)
        if meta and meta.get("folder_id") == fid:
            return lib
    return None


def ensure_unique_folder_id(
    library_path: Path, taken: set[str], embedding_model: str
) -> str | None:
    """Folder tag guaranteed not to collide with `taken`.

    If a folder was copied together with its hidden `.search_index`
    (meta.json included), two folders end up with the same folder_id —
    the tag must be unique, otherwise one folder's documents would look
    for PDFs in the other. In that case the tag is re-issued and
    meta.json rewritten.

    A read-only folder where meta.json cannot be written → None (no tag
    can be issued; such a folder does not index).
    """
    meta = read_meta(library_path)
    if meta is None:
        try:
            meta = ensure_meta(library_path, embedding_model)
        except OSError:
            return None
    fid = meta.get("folder_id")
    if not fid or fid in taken:
        fid = uuid.uuid4().hex
        meta["folder_id"] = fid
        try:
            save_json_atomic(index_root(library_path) / META_FILENAME, meta)
        except OSError:
            return None  # read-only folder — the collision cannot be fixed
    return fid


def has_complete_index(library_path: Path, slug: str) -> bool:
    """Does the document have a complete READABLE index (search minimum)?

    chunks.json + embeddings.json suffice: search reads only them;
    document.json/descriptions.json matter only for re-processing.
    Both files must parse as JSON: a broken/half-copied file is not
    adopted — the document would go ready and search would silently skip
    it. Chunk ids in both files must match: a pair from different
    generations (crash/race between two saves) would crash search with a
    KeyError.
    """
    d = doc_dir(library_path, slug)
    try:
        with open(d / "chunks.json", encoding="utf-8") as f:
            chunks = json.load(f)
        with open(d / "embeddings.json", encoding="utf-8") as f:
            emb = json.load(f)
        if not chunks or "model" not in emb or "items" not in emb:
            return False
        chunk_ids = {c["chunk_id"] for c in chunks}
        item_ids = {item["chunk_id"] for item in emb["items"]}
    except (OSError, json.JSONDecodeError, TypeError, KeyError):
        return False
    return chunk_ids == item_ids
