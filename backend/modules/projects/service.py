"""Scanning of the project archive folders: PDF walk, slugs.

There is no sheet/text classification anymore (step 3 of the universal
pipeline): all documents go through the shared per-page router; the scan
only counts pages and filters out broken PDFs.
"""

import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core import index_store, progress
from backend.core.ui_messages import msg
from backend.core.paths import PROJECTS_DATA_DIR
from backend.modules.projects.models import ProjectDocument
from backend.modules.projects.schemas import (
    ArchiveResponse,
    ArchiveScanSummary,
    ProjectDocumentOut,
    ProjectGroup,
)
from pdf_processing.page_count import count_pages
from pdf_processing.document_id import make_document_id


@dataclass
class FoundDocument:
    """A PDF found while scanning the archive (not in the DB yet)."""

    slug: str
    project: str
    relative_path: str
    page_count: int
    file_size: int
    file_mtime: float
    root: Path  # the project folder the file was found in


@dataclass
class UnreadableFile:
    """A PDF that is on disk but could not be opened (broken or locked).

    Отдельный тип, а не строка ошибки: sync должен знать slug и путь,
    чтобы показать документ со статусом error, а не удалить его как
    «пропавший с диска» — файл-то на месте.
    """

    slug: str
    project: str
    relative_path: str
    root: Path


@dataclass
class ArchiveScanResult:
    """Result of walking a project folder."""

    documents: list[FoundDocument]
    duplicates: list[str]  # relative_path of files whose slug is taken (namesakes)
    errors: list[str]  # files that could not be opened as PDFs
    unreadable: list[UnreadableFile]  # the same files, structured for sync


def make_project_slug(project: str, relative_path: str) -> str:
    """Slug of an archive document: {project}__{path inside the project}.

    The project is the name of the connected folder. The path, not just the
    file name — because same-named PDFs live in different subfolders of the
    project (TZ/, výkresy/). Slashes become spaces: make_document_id will
    collapse them to `_`.
    """
    return f"{make_document_id(project)}__{make_document_id(relative_path.replace('/', ' '))}"


def resolve_project_root(
    paths: list[Path], project: str, relative_path: str
) -> Path | None:
    """The project folder that actually holds the file at relative_path.

    Check both the folder name (= project name) and file presence: a
    relative_path like `TZ/tz.pdf` may exist in several projects at once,
    and without the name check the pipeline would process someone else's
    file. None — not found.
    """
    for root in paths:
        if root.name == project and (root / relative_path).exists():
            return root
    return None


def scan_archive(root: Path, seen_slugs: set[str] | None = None) -> ArchiveScanResult:
    """Walk a project folder and collect all PDFs.

    The whole connected folder = one project named after that folder; PDFs
    are taken from any depth, including the root. The file system is only
    read (principle #16). seen_slugs — the shared set of taken slugs (when
    walking several folders): namesakes between same-named project folders
    are a collision and go to duplicates.
    """
    documents: list[FoundDocument] = []
    duplicates: list[str] = []
    errors: list[str] = []
    unreadable: list[UnreadableFile] = []
    if seen_slugs is None:
        seen_slugs = set()

    project = root.name
    for pdf_path in sorted(root.rglob("*.pdf")):
        relative = pdf_path.relative_to(root)
        slug = make_project_slug(project, relative.as_posix())
        if slug in seen_slugs:
            duplicates.append(str(relative))
            continue

        try:
            page_count = count_pages(pdf_path)
            stat = pdf_path.stat()
        except Exception as error:
            errors.append(f"{relative}: {error}")
            seen_slugs.add(slug)
            unreadable.append(
                UnreadableFile(
                    slug=slug,
                    project=project,
                    relative_path=relative.as_posix(),
                    root=root,
                )
            )
            continue

        seen_slugs.add(slug)
        documents.append(
            FoundDocument(
                slug=slug,
                project=project,
                # as_posix: on Windows str() would give `\` — the frontend
                # splits by `/`, and root / path joins handle `/` on all OSes.
                relative_path=relative.as_posix(),
                page_count=page_count,
                file_size=stat.st_size,
                file_mtime=stat.st_mtime,
                root=root,
            )
        )

    return ArchiveScanResult(
        documents=documents,
        duplicates=duplicates,
        errors=errors,
        unreadable=unreadable,
    )


def _has_artifacts(root: Path, slug: str) -> bool:
    """Does the document have artifacts in either location?

    The folder (<root>/.search_index/{slug}) is the current home; the local
    projects_data pool is the legacy one (indexed by an old app version,
    or the project folder is read-only and migration failed).
    """
    return (
        index_store.has_index_files(root, slug) or (PROJECTS_DATA_DIR / slug).exists()
    )


def _wipe_artifacts(slug: str, root: Path | None) -> None:
    """Remove the document's artifacts from both locations (folder + legacy)."""
    if root is not None:
        shutil.rmtree(index_store.doc_dir(root, slug), ignore_errors=True)
    shutil.rmtree(PROJECTS_DATA_DIR / slug, ignore_errors=True)


def _dir_listing(base: Path) -> set[tuple[str, int]]:
    """Relative paths + sizes of all files under base (copy verification)."""
    return {
        (p.relative_to(base).as_posix(), p.stat().st_size)
        for p in base.rglob("*")
        if p.is_file()
    }


def _migrate_artifacts(slug: str, root: Path) -> bool:
    """Move legacy local artifacts into the project folder.

    Copy -> verify (same file list and sizes) -> remove the local copy.
    Any failure (read-only folder, network hiccup) rolls the copy back and
    keeps the local artifacts working — migration retries on a later scan.
    """
    local = PROJECTS_DATA_DIR / slug
    target = index_store.doc_dir(root, slug)
    if target.exists() or not local.is_dir():
        return False
    try:
        index_store.index_root(root).mkdir(exist_ok=True)
        shutil.copytree(local, target)
        if _dir_listing(local) != _dir_listing(target):
            raise OSError(f"incomplete copy of {slug}")
    except OSError:
        shutil.rmtree(target, ignore_errors=True)
        return False
    shutil.rmtree(local, ignore_errors=True)
    return True


def _maybe_migrate(root: Path, slug: str) -> bool:
    """Migrate at scan time only COMPLETE legacy artifacts.

    Partial folders (an error document's descriptions.json checkpoint) are
    migrated by reindex_document right before the pipeline resumes.
    """
    local = PROJECTS_DATA_DIR / slug
    if not ((local / "chunks.json").exists() and (local / "embeddings.json").exists()):
        return False
    return _migrate_artifacts(slug, root)


def _root_adoption(root: Path) -> tuple[bool, str | None]:
    """(can_adopt, readonly_error) of one project folder.

    Ensures the folder passport (meta.json) exists — same as the library:
    the passport records the embedding model, and foreign indexes are
    adopted only when the model matches ours. A folder where .search_index
    cannot be created is read-only: its documents cannot be indexed, so
    they get a clear error instead of an eternal silent "čeká".
    """
    from indexing.embeddings_index import EMBEDDING_MODEL

    meta = index_store.read_meta(root)
    if meta is None:
        try:
            meta = index_store.ensure_meta(root, EMBEDDING_MODEL)
        except OSError:
            return False, msg("lib.readonly_folder")
    return meta.get("embedding_model") == EMBEDDING_MODEL, None


def sync_archive(db: Session, roots: list[Path]) -> ArchiveScanSummary:
    """Scan all project folders and sync the project_documents table.

    New files — inserted with the "pending" status.
    Existing — path/pages updated (the file may have moved).
    Gone from disk — deleted from the DB together with the indexes (our
    artifacts in projects_data; the user's files are untouched). Removed a
    project from the folder -> "Skenovat" -> the project leaves search too.
    Reprocessing costs money again, so deleting a folder is a deliberate
    user action. An unavailable folder (network drive dropped) is NOT
    "gone": it goes to unavailable and cleanup is skipped entirely this scan.

    The slug (`{project}__{path}`) is unique across ALL folders: namesakes
    between same-named project folders are a collision, go to duplicates.
    """
    from backend.core import library_cache

    # A shared walk over all folders with one set of taken slugs.
    documents: list[FoundDocument] = []
    duplicates: list[str] = []
    errors: list[str] = []
    unreadable_files: list[UnreadableFile] = []
    unavailable: list[str] = []
    seen_slugs: set[str] = set()
    for root in roots:
        # An unavailable folder (network drive dropped) is indistinguishable
        # from an empty one: rglob on a nonexistent path silently yields an
        # empty list — and the cleanup below would wipe the records and
        # indexes of live documents.
        if not root.is_dir():
            unavailable.append(str(root))
            continue
        try:
            result = scan_archive(root, seen_slugs)
        except OSError:
            unavailable.append(str(root))
            continue
        documents.extend(result.documents)
        duplicates.extend(result.duplicates)
        errors.extend(result.errors)
        unreadable_files.extend(result.unreadable)

    existing = {doc.slug: doc for doc in db.scalars(select(ProjectDocument)).all()}
    found_slugs: set[str] = set()
    new_count = 0
    changed = 0
    adopted = 0
    migrated = False
    # Passport / read-only status once per folder, not per document.
    adoption = {root: _root_adoption(root) for root in roots if root.is_dir()}

    for found in documents:
        found_slugs.add(found.slug)
        doc = existing.get(found.slug)
        can_adopt, ro_error = adoption[found.root]
        if doc is None:
            if can_adopt and index_store.has_complete_index(found.root, found.slug):
                # A colleague already indexed this file in the shared
                # folder (or the folder was copied with its indexes) —
                # ready at once, at no cost.
                status = "ready"
                adopted += 1
            else:
                status = "error" if ro_error else "pending"
                new_count += 1
            db.add(
                ProjectDocument(
                    slug=found.slug,
                    project=found.project,
                    relative_path=found.relative_path,
                    # NOT NULL column without a default in live DBs (SQLite
                    # can't drop NOT NULL) — write the constant, no fork left.
                    doc_type="text",
                    page_count=found.page_count,
                    status=status,
                    error=ro_error if status == "error" else None,
                    file_size=found.file_size,
                    file_mtime=found.file_mtime,
                )
            )
        elif doc.status == "processing":
            # Being processed right now — update path/pages, do NOT touch
            # stat: a file replaced under the pipeline is caught by the
            # next scan.
            doc.relative_path = found.relative_path
            doc.page_count = found.page_count
        elif doc.file_size is None:
            # A row from an old version (no stat columns yet): fill in WITHOUT
            # resetting — otherwise the first scan after the upgrade would
            # dump the whole archive to pending, i.e. paying vision again.
            doc.relative_path = found.relative_path
            doc.page_count = found.page_count
            doc.file_size = found.file_size
            doc.file_mtime = found.file_mtime
            migrated |= _maybe_migrate(found.root, found.slug)
        elif (doc.file_size, doc.file_mtime) != (found.file_size, found.file_mtime):
            # The file was replaced (same path, new content): old chunks are
            # stale — clean up and return to pending. Indexing is paid, so
            # NO auto-start: the user clicks "Indexovat".
            _wipe_artifacts(found.slug, found.root)
            doc.relative_path = found.relative_path
            doc.page_count = found.page_count
            doc.status = "pending"
            doc.error = None
            doc.file_size = found.file_size
            doc.file_mtime = found.file_mtime
            changed += 1
        else:
            doc.relative_path = found.relative_path
            doc.page_count = found.page_count
            migrated |= _maybe_migrate(found.root, found.slug)
            if doc.status == "pending" and ro_error:
                # Stuck in "čeká" while the folder cannot be written —
                # rescan turns it into a clear error (mirrors the library).
                doc.status = "error"
                doc.error = ro_error
            if doc.status == "ready" and not _has_artifacts(found.root, found.slug):
                # "hotovo" without artifacts: reindex/delete rmtree first and
                # write the DB after, so a crash in between leaves the row
                # lying. Back to pending — the user clicks Indexovat.
                doc.status = "pending"
                doc.error = None

    # Файл на диске есть, но не открылся (битый или заблокирован другой
    # программой): документ остаётся в списке со статусом error, а не
    # исчезает как «удалённый». Существующую строку не трогаем: у error
    # уже есть точная причина из пайплайна, а ready продолжает искаться
    # по оплаченному индексу (файл может быть заблокирован временно).
    for bad in unreadable_files:
        found_slugs.add(bad.slug)
        if bad.slug not in existing:
            db.add(
                ProjectDocument(
                    slug=bad.slug,
                    project=bad.project,
                    relative_path=bad.relative_path,
                    doc_type="text",
                    page_count=0,
                    status="error",
                    error=msg("err.pdf_read"),
                )
            )
            new_count += 1

    removed = 0
    # Archive documents carry no folder label (slug = {project}__{path}), so
    # with ANY unavailable folder cleanup is skipped entirely — no way to
    # tell whose files are "gone". Once the drive is back, the next scan
    # finishes the cleanup.
    if not unavailable:
        for slug, doc in existing.items():
            if slug in found_slugs:
                continue
            if doc.status == "processing":
                continue  # being processed right now — don't pull the rug
            doc_root = next((r for r in roots if r.name == doc.project), None)
            _wipe_artifacts(slug, doc_root)
            db.delete(doc)
            removed += 1

    db.commit()
    if removed or changed or migrated or adopted:
        # Chunks disappeared from disk, moved between pools or appeared
        # without a pipeline run — the next question must see the truth.
        library_cache.invalidate()

    return ArchiveScanSummary(
        found=len(documents),
        new=new_count,
        missing=removed,
        changed=changed,
        adopted=adopted,
        duplicates=duplicates,
        errors=errors,
        unavailable=unavailable,
    )


def refresh_file_stat(doc: ProjectDocument, root: Path) -> None:
    """Record the CURRENT PDF stat before sending to the pipeline.

    The pipeline reads the file from disk at processing time — the stat in
    the DB must match exactly that version. Otherwise (file replaced between
    scan and launch) the next scan would consider the freshly paid index
    stale and needlessly reset it to pending.
    """
    try:
        stat = (root / doc.relative_path).stat()
    except OSError:
        return  # file vanished between resolve and stat — pipeline fails loudly
    doc.file_size = stat.st_size
    doc.file_mtime = stat.st_mtime


# Serializes indexing launches ("Indexovat" double-click): two concurrent
# calls would otherwise read the same pending rows before the other's
# commit — vision paid twice.
_start_indexing_lock = threading.Lock()


def start_archive_indexing(
    db: Session,
    paths: list[Path],
    executor: ThreadPoolExecutor,
) -> tuple[int, list[str]]:
    """Send pending archive documents to the pipeline.

    Status flips to processing right away — a repeated click will not send
    the same documents twice, and after a crash the startup resume picks
    them up. Each document's folder is found by its file's presence on disk.

    Each folder is locked with the inter-machine lock file before
    indexing (as in the library): a folder being indexed by another
    machine is skipped, its documents stay pending.

    Returns (submitted, list of "folder: who is indexing").
    """
    from backend.core import index_lock, library_cache
    from backend.modules.projects.pipeline import run_project_pipeline

    with _start_indexing_lock:
        pending = db.scalars(
            select(ProjectDocument).where(ProjectDocument.status == "pending")
        ).all()

        # Group pending by folder — one lock per folder.
        by_root: dict[Path, list[ProjectDocument]] = {}
        for doc in pending:
            root = resolve_project_root(paths, doc.project, doc.relative_path)
            if root is None:
                continue  # file not found in any folder — skip
            by_root.setdefault(root, []).append(doc)

        submitted = 0
        locked: list[str] = []
        adopted_any = False
        for root, docs in by_root.items():
            # Re-check right before the paid run: a colleague may have
            # indexed a file after our scan — adopt for free instead
            # (mirrors the library's pending adoption, 785ea29).
            can_adopt, _ = _root_adoption(root)
            to_run: list[ProjectDocument] = []
            for doc in docs:
                if can_adopt and index_store.has_complete_index(root, doc.slug):
                    doc.status = "ready"
                    doc.error = None
                    adopted_any = True
                else:
                    to_run.append(doc)
            db.commit()  # adopted statuses
            if not to_run:
                continue  # everything adopted — no folder lock needed

            busy_owner = index_lock.acquire(root)
            if busy_owner is not None:
                locked.append(f"{root.name}: {busy_owner}")
                continue  # held by another machine — leave documents pending
            index_lock.register(root, len(to_run))
            for doc in to_run:
                refresh_file_stat(doc, root)
                doc.status = "processing"
            db.commit()
            for doc in to_run:
                executor.submit(
                    run_project_pipeline,
                    doc.slug,
                    str(root / doc.relative_path),
                    str(root),
                )
                submitted += 1
        if adopted_any:
            # Ready documents appeared without a pipeline run — the next
            # question must see them.
            library_cache.invalidate()
        return submitted, locked


class DocumentBusyError(Exception):
    """Operation rejected: the archive document is being processed right now.

    Reindexing while the background pipeline runs creates a race: the
    pipeline would finish writing artifacts AFTER the rmtree — files and
    status would drift apart.
    """


def reindex_document(
    db: Session,
    slug: str,
    paths: list[Path],
    executor: ThreadPoolExecutor,
) -> ProjectDocument:
    """Fully reprocess an archive document: old artifacts are removed.

    Needed after a pipeline change (step 3: former sheet documents) or when
    the user replaced the PDF's content. The PDF itself in the archive
    folder is NOT touched. Artifacts live in <root>/.search_index/{slug}
    (plus the legacy local pool for old installs).
    """
    from backend.core import index_lock, library_cache
    from backend.modules.projects.pipeline import run_project_pipeline

    doc = db.scalar(select(ProjectDocument).where(ProjectDocument.slug == slug))
    if doc is None:
        raise ValueError(msg("projects.doc_not_found", slug=slug))
    if doc.status == "processing":
        raise DocumentBusyError(msg("lib.doc_busy", slug=slug))

    root = resolve_project_root(paths, doc.project, doc.relative_path)
    if root is None:
        raise ValueError(msg("projects.pdf_not_found", path=doc.relative_path))

    # The inter-machine folder lock, as in regular indexing: without it
    # reindex would write into .search_index in parallel with another machine.
    busy = index_lock.acquire(root)
    if busy is not None:
        raise DocumentBusyError(msg("lib.folder_busy", owner=busy))
    index_lock.register(root, 1)

    # A ready document is rebuilt from scratch. A failed one (error) —
    # CONTINUE from the checkpoint: descriptions of the paid pages sit in
    # descriptions.json, the describe resume skips them. Live case
    # 2026-08-02: vision failed on page 166 of ~189 — rmtree was throwing
    # away ~165 paid pages. A legacy local checkpoint moves into the folder
    # first — the pipeline reads/writes only <root>/.search_index/{slug}.
    if doc.status == "ready":
        _wipe_artifacts(slug, root)
    else:
        _migrate_artifacts(slug, root)

    doc.status = "processing"
    doc.error = None
    refresh_file_stat(doc, root)
    db.commit()

    # Old chunks are already gone from disk — drop them from the cache now,
    # without waiting for reprocessing to finish (the pipeline invalidates
    # the cache again when the document is ready).
    library_cache.invalidate()

    executor.submit(
        run_project_pipeline, slug, str(root / doc.relative_path), str(root)
    )
    return doc


def toggle_pin(db: Session, slug: str) -> ProjectDocument:
    """Toggle the pinned state of an archive document. ValueError if not found."""
    doc = db.scalar(select(ProjectDocument).where(ProjectDocument.slug == slug))
    if doc is None:
        raise ValueError(msg("projects.doc_not_found", slug=slug))
    doc.pinned = not doc.pinned
    db.commit()
    return doc


def build_archive_response(db: Session, paths: list[str]) -> ArchiveResponse:
    """Archive documents from the DB, grouped by project (for the UI)."""
    docs = db.scalars(
        select(ProjectDocument).order_by(
            ProjectDocument.project, ProjectDocument.relative_path
        )
    ).all()

    groups: dict[str, list[ProjectDocumentOut]] = {}
    for doc in docs:
        out = ProjectDocumentOut.model_validate(doc)
        out.progress = progress.get_progress(doc.slug)
        groups.setdefault(doc.project, []).append(out)

    return ArchiveResponse(
        paths=paths,
        projects=[
            ProjectGroup(name=name, documents=items) for name, items in groups.items()
        ],
    )
