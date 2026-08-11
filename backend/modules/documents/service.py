"""Business logic of the documents module."""

import json
import re
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core import (
    cancel,
    index_lock,
    index_store,
    library_cache,
    parse_subprocess,
    progress,
)
from backend.core.ui_messages import msg
from backend.modules.documents.models import Document
from backend.modules.documents.pipeline import run_pipeline_locked
from common.jsonio import save_json_atomic


# A slug is always `make_document_id` output, optionally prefixed with a
# folder_id (uuid4 hex) — both are [a-z0-9_] only.
_SAFE_SLUG_RE = re.compile(r"^[a-z0-9_]+$")


class DocumentBusyError(Exception):
    """Operation rejected: the document is being processed right now.

    Delete/reindex/relink during a running pipeline race it: the pipeline
    would finish writing artifacts AFTER the rmtree, and the next scan
    would adopt the deleted document back (double payment).
    """


def _ensure_not_processing(doc: Document) -> None:
    """Raise DocumentBusyError when the pipeline is working on the document."""
    if doc.status == "processing":
        raise DocumentBusyError(msg("lib.doc_busy", slug=doc.slug))


def _ensure_safe_slug(slug: str) -> None:
    """Reject a slug that would work as a path when glued to a folder.

    The client sends new_slug for relink and it ends up in the DB, from
    where delete/reindex build their rmtree target. `..`, a separator or
    an absolute path would take those operations outside .search_index —
    decision #16 says the user's files are never touched.
    """
    if not _SAFE_SLUG_RE.match(slug):
        raise ValueError(f"Invalid slug: {slug!r}")


def _artifact_dirs(slug: str, library_path: Path | None) -> list[Path]:
    """The document's artifact folder inside its library's .search_index.

    A list (not a single path): callers clean every candidate and need
    not know there is currently one; a detached folder yields an empty
    list, not an error.
    """
    if library_path is None:
        return []
    return [index_store.doc_dir(library_path, slug)]


def _doc_folder(paths: list[Path], slug: str) -> Path | None:
    """The library folder owning the document (by the slug tag)."""
    return index_store.resolve_folder(paths, slug)


def _ensure_folder_not_locked(library_path: Path | None) -> None:
    """Raise DocumentBusyError when ANOTHER machine is indexing the folder.

    delete/relink mutate the shared .search_index — under a foreign
    pipeline an rmtree/rename would break its writes (paid vision lost).
    The lock is only checked, NOT taken: acquire+done would corrupt the
    in-flight counter of documents our own machine is indexing.
    """
    if library_path is None:
        return  # library folder unknown — nothing to coordinate
    busy = index_lock.holder(library_path)
    if busy is not None:
        raise DocumentBusyError(msg("lib.folder_busy", owner=busy))


def list_documents(db: Session) -> list[Document]:
    """All library documents ordered by creation date."""
    stmt = select(Document).order_by(Document.created_at)
    return list(db.scalars(stmt))


def reindex_document(
    db: Session,
    slug: str,
    paths: list[Path],
    executor: ThreadPoolExecutor,
) -> Document:
    """Fully re-process a document: drop old artifacts, run the pipeline.

    Needed when the user replaced the PDF content (same file name). Old
    chunks/embeddings are stale — thrown away and rebuilt. The PDF itself
    is untouched.
    """
    doc = db.scalar(select(Document).where(Document.slug == slug))
    if doc is None:
        raise ValueError(f"Document {slug} not found")
    _ensure_not_processing(doc)
    if doc.relative_path is None:
        raise ValueError(f"Document {slug} has no relative_path — scan first")

    library_path = _doc_folder(paths, slug)
    if library_path is None:
        raise ValueError(f"The folder of document {slug} is not attached")

    pdf_path = library_path / doc.relative_path
    if not pdf_path.exists():
        raise ValueError(f"PDF not found in the library: {pdf_path}")

    # The inter-machine folder lock, as in regular indexing: without it
    # reindex would write into .search_index in parallel with another machine.
    busy = index_lock.acquire(library_path)
    if busy is not None:
        raise DocumentBusyError(msg("lib.folder_busy", owner=busy))

    # A ready document rebuilds from scratch. A failed one RESUMES from
    # the descriptions.json checkpoint: describe skips the already-paid
    # pages (live case 2026-08-02 — a vision hiccup on a single page).
    if doc.status == "ready":
        for artifacts_dir in _artifact_dirs(slug, library_path):
            if artifacts_dir.exists():
                shutil.rmtree(artifacts_dir)

    doc.status = "processing"
    doc.error_message = None
    db.commit()

    # The old chunks are already gone from disk — drop them from the
    # cache now; the pipeline invalidates again when the document is ready.
    library_cache.invalidate()

    # Lazy import: embeddings_index pulls in openai/tiktoken.
    from indexing.embeddings_index import EMBEDDING_MODEL

    index_store.ensure_meta(library_path, EMBEDDING_MODEL)
    index_lock.register(library_path, 1)
    # «čeká ve frontě» до входа в шлюз parse (как при обычном старте).
    progress.set_progress(slug, msg("progress.queued"))
    executor.submit(
        run_pipeline_locked,
        library_path,
        slug,
        str(pdf_path),
        index_store.doc_dir(library_path, slug),
    )
    return doc


def stop_document(db: Session, slug: str) -> None:
    """⏹: остановить индексацию документа (кооперативно, см. core/cancel).

    В очереди executor (пайплайн не начался) — сразу вернуть в čeká:
    задача выйдет молча, когда дойдёт очередь. Реально работает — взвести
    флаг («zastavuje se…»), пайплайн выйдет на безопасной точке; воркер
    parse убивается сразу, если жуёт именно этот документ. Не-processing
    документ — тихий no-op (кнопка могла «прокиснуть»).
    """
    doc = db.scalar(select(Document).where(Document.slug == slug))
    if doc is None or doc.status != "processing":
        return
    cancel.request(slug)
    if cancel.is_running(slug):
        progress.set_progress(slug, msg("progress.stopping"))
        parse_subprocess.kill_if_parsing(slug)
    else:
        doc.status = "pending"
        doc.error_message = None
        db.commit()
        progress.clear_progress(slug)


def delete_document(db: Session, slug: str, paths: list[Path] | None = None) -> None:
    """Remove a document from the index: the DB row and our artifacts.

    The PDF in the user's folder is untouched — the app never modifies
    user files; it writes only inside its own .search_index subfolder.
    """
    doc = db.scalar(select(Document).where(Document.slug == slug))
    if doc is None:
        raise ValueError(f"Document {slug} not found")
    _ensure_not_processing(doc)

    library_path = _doc_folder(paths or [], slug)
    _ensure_folder_not_locked(library_path)
    for artifacts_dir in _artifact_dirs(slug, library_path):
        if artifacts_dir.exists():
            shutil.rmtree(artifacts_dir)

    db.delete(doc)
    db.commit()
    library_cache.invalidate()  # the document left the disk — refresh


def toggle_pin(db: Session, slug: str) -> Document:
    """Toggle the pin. ValueError when the document is missing."""
    doc = db.scalar(select(Document).where(Document.slug == slug))
    if doc is None:
        raise ValueError(f"Document {slug} not found")
    doc.pinned = not doc.pinned
    db.commit()
    return doc


def relink_document(
    db: Session, old_slug: str, new_slug: str, paths: list[Path] | None = None
) -> Document:
    """Move an existing index from the old slug to the new one (rename).

    The user renamed a PDF in the library folder. To avoid paying vision
    again for the same document, the ready chunks and embeddings move to
    the new name.

    Steps:
    1. Rename the artifact folder {old_slug}/ -> {new_slug}/.
    2. In chunks.json replace document_id and the chunk_id prefix.
    3. In embeddings.json replace the chunk_id prefix.
    4. Update Document.slug in the DB.
    """
    if old_slug == new_slug:
        raise ValueError("old_slug and new_slug are identical")
    _ensure_safe_slug(new_slug)

    doc = db.scalar(select(Document).where(Document.slug == old_slug))
    if doc is None:
        raise ValueError(f"Document {old_slug} not found in the DB")
    _ensure_not_processing(doc)

    conflicting = db.scalar(select(Document).where(Document.slug == new_slug))
    if conflicting is not None:
        raise ValueError(f"A document with slug {new_slug} already exists")

    # The index moves within the pool where it actually lives.
    library_path = _doc_folder(paths or [], old_slug)
    _ensure_folder_not_locked(library_path)
    old_dir = next(
        (d for d in _artifact_dirs(old_slug, library_path) if d.exists()), None
    )
    if old_dir is None:
        raise ValueError(f"Artifact folder of {old_slug} not found on disk")
    new_dir = old_dir.parent / new_slug
    if new_dir.exists():
        raise ValueError(f"Folder {new_dir} already exists — conflict")

    # 1. Rename the artifact folder.
    old_dir.rename(new_dir)

    # 2. chunks.json: swap document_id and the chunk_id prefix.
    chunks_path = new_dir / "chunks.json"
    if chunks_path.exists():
        with open(chunks_path, encoding="utf-8") as f:
            chunks = json.load(f)
        for chunk in chunks:
            chunk["document_id"] = new_slug
            chunk["chunk_id"] = _replace_prefix(chunk["chunk_id"], old_slug, new_slug)
        save_json_atomic(chunks_path, chunks)

    # 3. embeddings.json: chunk_id inside items.
    emb_path = new_dir / "embeddings.json"
    if emb_path.exists():
        with open(emb_path, encoding="utf-8") as f:
            emb = json.load(f)
        for item in emb.get("items", []):
            item["chunk_id"] = _replace_prefix(item["chunk_id"], old_slug, new_slug)
        save_json_atomic(emb_path, emb)

    # 4. Update the slug in the DB.
    doc.slug = new_slug
    db.commit()
    library_cache.invalidate()  # document_id/chunk_id changed — refresh
    return doc


def _replace_prefix(value: str, old: str, new: str) -> str:
    """Replace the old prefix with the new; no prefix — returned as is."""
    if value.startswith(old):
        return new + value[len(old) :]
    return value
