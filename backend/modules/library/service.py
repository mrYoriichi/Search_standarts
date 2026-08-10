"""Business logic of the library module.

Scans the library folder and builds a tree, marks PDFs with their DB
status (if already indexed). Opens a file in the system viewer after
checking that the path is inside the library.
"""

import json
import os
import platform
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core import index_lock, index_store, library_cache, progress
from backend.core.ui_messages import msg
from backend.modules.documents.models import Document
from backend.modules.documents.pipeline import run_pipeline_locked
from backend.modules.library.schemas import (
    LibraryFile,
    LibraryFolder,
    LibraryResponse,
    OrphanDocument,
    ScanSummary,
)
from pdf_processing.page_count import count_pages
from pdf_processing.document_id import make_document_id


# PDF status resolver by slug: (status, pinned, error, progress). Tells the
# user's pool (status from the DB) apart from the shared base (status by index
# presence), so the tree is built by a single _walk. error — failure reason,
# progress — current processing stage (both only for the user's pool, else None).
StatusResolver = Callable[[str], tuple[str | None, bool, str | None, str | None]]
# Document id from a file name (scoped slugs need the folder label).
SlugOf = Callable[[str], str]


def _unique_dirs(paths: list[Path]) -> list[Path]:
    """Drop repeats of the same physical folder (symlink/second path)."""
    result: list[Path] = []
    for p in paths:
        if any(index_store.same_dir(p, seen) for seen in result):
            continue
        result.append(p)
    return result


def _folder_ids(paths: list[Path]) -> dict[Path, str | None]:
    """Labels of all folders, guaranteed unique among themselves.

    If a folder was copied together with `.search_index` (same folder_id),
    the collision is fixed: the second folder gets a new label (see
    index_store.ensure_unique_folder_id). Persisted in meta.json so that all
    readers (tree, resolve_folder, cache) see the corrected labels.

    The same PHYSICAL folder under two paths (symlink, double mount) is
    NOT a collision: both entries share one label, meta.json stays intact.
    Otherwise the label would be reissued in a "ping-pong" on every request
    and documents would become orphans.
    """
    from indexing.embeddings_index import EMBEDDING_MODEL

    ids: dict[Path, str | None] = {}
    taken: dict[str, Path] = {}
    for lib in paths:
        meta = index_store.read_meta(lib)
        existing = (meta or {}).get("folder_id")
        if (
            existing
            and existing in taken
            and index_store.same_dir(lib, taken[existing])
        ):
            ids[lib] = existing
            continue
        fid = index_store.ensure_unique_folder_id(lib, set(taken), EMBEDDING_MODEL)
        ids[lib] = fid
        if fid:
            taken[fid] = lib
    return ids


def _slug_fn(folder_id: str | None) -> SlugOf:
    """Build a "file name -> document id" function for a specific folder."""

    def slug_of(name: str) -> str:
        base = make_document_id(name)
        return index_store.scoped_slug(folder_id, base) if folder_id else base

    return slug_of


def build_library_response(paths: list[Path], db: Session) -> LibraryResponse:
    """Tree of all library folders + the list of orphan documents (no file).

    Every connected folder is a node of its own under a synthetic root
    "Knihovny" — even a single one, so its files are grouped under the
    folder name instead of lying loose at the top level.
    """
    paths = _unique_dirs(paths)
    docs_by_slug = {doc.slug: doc for doc in db.scalars(select(Document)).all()}

    def resolve(slug: str) -> tuple[str | None, bool, str | None, str | None]:
        doc = docs_by_slug.get(slug)
        if doc is None:
            return (None, False, None, None)
        return (doc.status, doc.pinned, doc.error_message, progress.get_progress(slug))

    folder_ids = _folder_ids(paths)
    subtrees = []
    for lib in paths:
        try:
            subtrees.append(_walk(lib, resolve, _slug_fn(folder_ids[lib])))
        except OSError:
            # Folder unavailable (network drive dropped) — show an empty
            # node with a mark; other folders and the whole page live on.
            subtrees.append(
                LibraryFolder(
                    name=msg("lib.folder_unavailable", name=lib.name),
                    path=str(lib),
                    folders=[],
                    files=[],
                )
            )
    root = LibraryFolder(name=msg("lib.tree_root"), path="", folders=subtrees, files=[])

    seen_slugs: set[str] = set()
    _collect_slugs(root, seen_slugs)
    orphans = [
        OrphanDocument(slug=doc.slug, title=doc.title, status=doc.status)
        for doc in docs_by_slug.values()
        if doc.slug not in seen_slugs
    ]
    return LibraryResponse(tree=root, orphans=orphans)


def _collect_slugs(folder: LibraryFolder, out: set[str]) -> None:
    for file in folder.files:
        out.add(file.slug)
    for sub in folder.folders:
        _collect_slugs(sub, out)


def _walk(folder: Path, resolve: StatusResolver, slug_of: SlugOf) -> LibraryFolder:
    folders: list[LibraryFolder] = []
    files: list[LibraryFile] = []
    for entry in sorted(folder.iterdir(), key=lambda p: p.name.lower()):
        # Skip hidden files and macOS system junk.
        if entry.name.startswith("."):
            continue
        if entry.is_dir():
            folders.append(_walk(entry, resolve, slug_of))
        elif entry.suffix.lower() == ".pdf":
            slug = slug_of(entry.name)
            status, pinned, error, doc_progress = resolve(slug)
            files.append(
                LibraryFile(
                    name=entry.name,
                    path=str(entry),
                    slug=slug,
                    status=status,
                    pinned=pinned,
                    error=error,
                    progress=doc_progress,
                )
            )
    return LibraryFolder(
        name=folder.name, path=str(folder), folders=folders, files=files
    )


def find_pdf_by_slug(paths: list[Path], slug: str) -> Path | None:
    """Search the library folders for a PDF whose document id matches the slug.

    The folder label from the slug maps to a specific folder
    (index_store.resolve_folder); we search only there — same-named files from
    other folders cannot be confused. Without a label (legacy slug), search
    all folders by file name.
    """
    folder = index_store.resolve_folder(paths, slug)
    if folder is not None:
        fid = index_store.folder_id_of(slug)
        for entry in folder.rglob("*.pdf"):
            if entry.name.startswith("."):
                continue
            if index_store.scoped_slug(fid, make_document_id(entry.name)) == slug:
                return entry
        return None
    # Legacy slug without a folder label — search all folders by file name.
    for lib in paths:
        for entry in lib.rglob("*.pdf"):
            if entry.name.startswith("."):
                continue
            if make_document_id(entry.name) == slug:
                return entry
    return None


def _pdf_by_stored_path(db: Session, paths: list[Path], slug: str) -> Path | None:
    """The document's PDF by the path the scan recorded for it.

    find_pdf_by_slug returns the FIRST file whose name gives this slug, so
    same-named PDFs in two subfolders make it open the wrong one. The exact
    path is already in the DB. It goes stale after a relink (relative_path
    is not updated until the next scan) — hence the existence check, with
    the search as fallback.
    """
    doc = db.scalar(select(Document).where(Document.slug == slug))
    if doc is None or not doc.relative_path:
        return None
    folder = index_store.resolve_folder(paths, slug)
    for lib in [folder] if folder is not None else paths:
        pdf_path = lib / doc.relative_path
        if pdf_path.exists():
            return pdf_path
    return None


def resolve_pdf_by_slug(db: Session, slug: str) -> Path | None:
    """Path to a document's PDF by slug — across ALL pools (library + archive).

    The only place aware of both pools: used by PDF serving
    (`GET /library/pdf/{slug}`) and strong search (rendering source pages).
    """
    from backend.modules.projects import service as projects_service
    from backend.modules.projects.models import ProjectDocument
    from backend.modules.settings import service as settings_service

    library_paths = [Path(p) for p in settings_service.get_library_paths(db)]
    if library_paths:
        pdf_path = _pdf_by_stored_path(db, library_paths, slug) or find_pdf_by_slug(
            library_paths, slug
        )
        if pdf_path is not None:
            return pdf_path

    # Project archive: the DB knows relative_path, the folder — by file presence.
    projects_paths = [Path(p) for p in settings_service.get_projects_paths(db)]
    pdoc = db.scalar(select(ProjectDocument).where(ProjectDocument.slug == slug))
    if projects_paths and pdoc is not None:
        root = projects_service.resolve_project_root(
            projects_paths, pdoc.project, pdoc.relative_path
        )
        if root is not None:
            return root / pdoc.relative_path
    return None


def scan_library(paths: list[Path], db: Session) -> ScanSummary:
    """Scan all library folders: NEW PDFs are only registered (pending).

    Scanning is free (discovery), indexing is paid (vision LLM) — hence two
    deliberate user steps: Skenovat -> "čeká" list -> Indexovat
    (start_indexing).

    Document id = `{folder_id}__{file}`, so same-named files in DIFFERENT
    folders are different documents. The only remaining collision is a name
    clash WITHIN one folder: such files are skipped, the user is asked to
    rename them.

    For each PDF:
      - if a DB record exists (by slug) — update relative_path after a move;
      - if not, but `.search_index/{slug}` holds a complete index on our
        model — "adopt" it (ready at once, at no cost);
      - otherwise — Document(status='pending'), NOT sent to the pipeline.
    """
    from indexing.embeddings_index import EMBEDDING_MODEL

    paths = _unique_dirs(paths)
    docs_by_slug = {doc.slug: doc for doc in db.scalars(select(Document)).all()}
    summary = ScanSummary(created=0, already_indexed=0, adopted=0, duplicates=[])
    any_adopted = False
    folder_ids = _folder_ids(paths)

    for library_path in paths:
        folder_id = folder_ids[library_path]
        slug_of = _slug_fn(folder_id)
        # No folder_id — .search_index could not be written to the folder
        # (read-only, network drive without permissions). Instead of an
        # eternal silent "čeká", mark documents failed with a clear reason.
        ro_error = None if folder_id else msg("lib.readonly_folder")
        # Foreign indexes can be adopted only on our embedding model.
        meta = index_store.read_meta(library_path)
        can_adopt = meta is not None and meta.get("embedding_model") == EMBEDDING_MODEL

        try:
            pdf_paths = [
                p
                for p in sorted(library_path.rglob("*.pdf"))
                if not p.name.startswith(".")
            ]
        except OSError:
            continue  # folder unavailable (network drive) — others scan on
        # How many files map to each slug WITHIN this folder. >1 — name clash.
        slug_counts: dict[str, int] = {}
        for p in pdf_paths:
            slug_counts[slug_of(p.name)] = slug_counts.get(slug_of(p.name), 0) + 1

        for pdf_path in pdf_paths:
            slug = slug_of(pdf_path.name)
            # as_posix: on Windows str() would give `\`; store paths uniformly.
            relative_path = pdf_path.relative_to(library_path).as_posix()

            if slug_counts[slug] > 1:
                summary.duplicates.append(relative_path)
                continue

            existing = docs_by_slug.get(slug)
            if existing is not None:
                if existing.relative_path != relative_path:
                    existing.relative_path = relative_path
                if ro_error and existing.status == "pending":
                    # Document stuck in "čeká" before the fix — rescan heals.
                    existing.status = "failed"
                    existing.error_message = ro_error
                if existing.status == "ready" and not index_store.has_index_files(
                    library_path, slug
                ):
                    # "hotovo" without an index on disk: delete/reindex/relink
                    # write the DB after the rmtree, so a crash in between
                    # leaves the row lying. Back to čeká — Indexovat rebuilds
                    # it (and adopts for free if the files are actually there).
                    existing.status = "pending"
                    existing.error_message = None
                summary.already_indexed += 1
                continue

            if can_adopt and index_store.has_complete_index(library_path, slug):
                doc = Document(
                    slug=slug,
                    title=_adopted_title(library_path, slug) or pdf_path.stem,
                    status="ready",
                    relative_path=relative_path,
                    page_count=_safe_count_pages(pdf_path),
                )
                db.add(doc)
                db.commit()
                summary.adopted += 1
                any_adopted = True
                continue

            doc = Document(
                slug=slug,
                title=pdf_path.stem,  # the pipeline will set the real title
                status="failed" if ro_error else "pending",
                relative_path=relative_path,
                error_message=ro_error,
            )
            db.add(doc)
            db.commit()
            summary.created += 1

    db.commit()
    if any_adopted:
        # Ready documents appeared in the pool without a pipeline run —
        # the next question must see them.
        library_cache.invalidate()
    return summary


def _safe_count_pages(pdf_path: Path) -> int:
    """PDF page count; a broken/unreadable file counts as 0 — don't fail the scan.

    Such a file will still fail with a clear error in the pipeline/adoption;
    the page counter is not noticeably hurt by the zero.
    """
    try:
        return count_pages(pdf_path)
    except Exception:  # pylint: disable=broad-except
        return 0


def _ensure_page_count(doc: Document, library_path: Path) -> int:
    """Document page count; computed and stored on first access."""
    if doc.page_count is not None:
        return doc.page_count
    if not doc.relative_path:
        return 0
    doc.page_count = _safe_count_pages(library_path / doc.relative_path)
    return doc.page_count


def _adopted_title(library_path: Path, slug: str) -> str | None:
    """Title of an adopted document from descriptions.json, if present there."""
    path = index_store.doc_dir(library_path, slug) / "descriptions.json"
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f).get("document_title") or None
    except (OSError, json.JSONDecodeError):
        return None


# Serializes concurrent POST /library/index (double-click): without this both
# requests managed to read the same pending rows before the other's commit —
# a document went to the pipeline twice (vision paid twice).
_start_indexing_lock = threading.Lock()


def start_indexing(
    paths: list[Path],
    db: Session,
    executor: ThreadPoolExecutor,
) -> tuple[int, list[str]]:
    """Send pending documents to the pipeline, each into its own folder.

    Status flips to processing right away: a repeated "Indexovat" click will
    not send the same documents twice (vision paid twice), and after an app
    crash the startup resume picks them up. Artifacts are written to
    `<document folder>/.search_index/{slug}`.

    The folder is locked with a lock file before indexing: if another machine
    is already indexing it (shared network folder) — its documents are left
    pending and we report who is busy.

    Returns (submitted, list of "folder: who is indexing").
    """
    from indexing.embeddings_index import EMBEDDING_MODEL

    with _start_indexing_lock:
        pending = db.scalars(select(Document).where(Document.status == "pending")).all()

        # Group pending by folder — one lock per folder.
        by_folder: dict[Path, list[Document]] = {}
        for doc in pending:
            library_path = index_store.resolve_folder(paths, doc.slug)
            if library_path is None:
                continue  # the document's folder is disconnected — skip
            by_folder.setdefault(library_path, []).append(doc)

        submitted = 0
        locked: list[str] = []
        any_adopted = False
        for library_path, docs in by_folder.items():
            # Re-check BEFORE launch: a colleague may have finished indexing a
            # document in the shared folder after our scan (the pending row
            # didn't see it). A ready index is adopted for free; forced
            # reprocessing stays on the 🔄 button.
            meta = index_store.read_meta(library_path)
            can_adopt = (
                meta is not None and meta.get("embedding_model") == EMBEDDING_MODEL
            )
            to_run: list[Document] = []
            for doc in docs:
                if can_adopt and index_store.has_complete_index(library_path, doc.slug):
                    _ensure_page_count(doc, library_path)
                    doc.status = "ready"
                    doc.error_message = None
                    doc.title = _adopted_title(library_path, doc.slug) or doc.title
                    any_adopted = True
                else:
                    to_run.append(doc)
            for doc in to_run:
                _ensure_page_count(doc, library_path)  # feeds the page counter
            db.commit()  # adopted statuses + filled-in page counts
            if not to_run:
                continue  # everything adopted — no folder lock needed
            docs = to_run

            busy_owner = index_lock.acquire(library_path)
            if busy_owner is not None:
                locked.append(f"{library_path.name}: {busy_owner}")
                continue  # held by another machine — leave documents pending
            index_lock.register(library_path, len(docs))
            for doc in docs:
                doc.status = "processing"
            db.commit()
            for doc in docs:
                pdf_path = (
                    str(library_path / doc.relative_path) if doc.relative_path else None
                )
                executor.submit(
                    run_pipeline_locked,
                    library_path,
                    doc.slug,
                    pdf_path,
                    index_store.doc_dir(library_path, doc.slug),
                )
                submitted += 1
        if any_adopted:
            # Ready documents appeared in the pool without the pipeline — the
            # next question must see them (mirrors scan_library).
            library_cache.invalidate()
        return submitted, locked


def _is_within(target: Path, root: Path) -> bool:
    """Is target inside root (or equal to it)?"""
    try:
        target.relative_to(root)
        return True
    except ValueError:
        return False


def open_file(paths: list[Path], file_path: str) -> None:
    """Open a PDF in the system viewer.

    Security: the file must be inside one of the library folders,
    otherwise the API could open anything on the disk.
    """
    target = Path(file_path).expanduser().resolve()
    if not any(_is_within(target, lib) for lib in paths):
        raise ValueError(msg("lib.file_outside"))
    if not target.is_file():
        raise ValueError(msg("lib.file_not_found", path=target))

    system = platform.system()
    if system == "Darwin":
        subprocess.run(["open", str(target)], check=False)
    elif system == "Windows":
        # startfile = ShellExecute, opens the file with its associated app.
        # NOT the shell command `start`: through it a file name like
        # `a&calc.pdf` from a shared folder would execute a command.
        os.startfile(str(target))  # exists only on Windows
    else:
        subprocess.run(["xdg-open", str(target)], check=False)
