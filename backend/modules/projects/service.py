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
from pdf_processing.parser import make_document_id


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
class ArchiveScanResult:
    """Result of walking a project folder."""

    documents: list[FoundDocument]
    duplicates: list[str]  # relative_path of files whose slug is taken (namesakes)
    errors: list[str]  # files that could not be opened as PDFs


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

    existing = {doc.slug: doc for doc in db.scalars(select(ProjectDocument)).all()}
    found_slugs: set[str] = set()
    new_count = 0
    changed = 0
    migrated = False

    for found in documents:
        found_slugs.add(found.slug)
        doc = existing.get(found.slug)
        if doc is None:
            db.add(
                ProjectDocument(
                    slug=found.slug,
                    project=found.project,
                    relative_path=found.relative_path,
                    # NOT NULL column without a default in live DBs (SQLite
                    # can't drop NOT NULL) — write the constant, no fork left.
                    doc_type="text",
                    page_count=found.page_count,
                    status="pending",
                    file_size=found.file_size,
                    file_mtime=found.file_mtime,
                )
            )
            new_count += 1
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
            if doc.status == "ready" and not _has_artifacts(found.root, found.slug):
                # "hotovo" without artifacts: reindex/delete rmtree first and
                # write the DB after, so a crash in between leaves the row
                # lying. Back to pending — the user clicks Indexovat.
                doc.status = "pending"
                doc.error = None

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
    if removed or changed or migrated:
        # Chunks disappeared from disk or moved between pools — the search
        # cache must not serve stale locations.
        library_cache.invalidate()

    return ArchiveScanSummary(
        found=len(documents),
        new=new_count,
        missing=removed,
        changed=changed,
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
) -> int:
    """Send pending archive documents to the pipeline.

    Status flips to processing right away — a repeated click will not send
    the same documents twice, and after a crash the startup resume picks
    them up. Each document's folder is found by its file's presence on disk.

    Returns the number of submitted documents.
    """
    from backend.modules.projects.pipeline import run_project_pipeline

    with _start_indexing_lock:
        pending = db.scalars(
            select(ProjectDocument).where(ProjectDocument.status == "pending")
        ).all()

        submitted = 0
        for doc in pending:
            root = resolve_project_root(paths, doc.project, doc.relative_path)
            if root is None:
                continue  # file not found in any folder — skip
            refresh_file_stat(doc, root)
            doc.status = "processing"
            db.commit()
            executor.submit(
                run_project_pipeline, doc.slug, str(root / doc.relative_path), str(root)
            )
            submitted += 1
        return submitted


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
    from backend.core import library_cache
    from backend.modules.projects.pipeline import run_project_pipeline

    doc = db.scalar(select(ProjectDocument).where(ProjectDocument.slug == slug))
    if doc is None:
        raise ValueError(msg("projects.doc_not_found", slug=slug))
    if doc.status == "processing":
        raise DocumentBusyError(msg("lib.doc_busy", slug=slug))

    root = resolve_project_root(paths, doc.project, doc.relative_path)
    if root is None:
        raise ValueError(msg("projects.pdf_not_found", path=doc.relative_path))

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
