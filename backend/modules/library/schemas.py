"""Pydantic schemas for the library module endpoints.

The library folder is returned as a tree: each folder contains
nested folders and PDF files. A PDF has a processing status (if there is
a DB record), otherwise None ("not indexed").
"""

from pydantic import BaseModel


class LibraryFile(BaseModel):
    """A PDF file in the library folder."""

    name: str
    path: str  # absolute path to the file on disk
    slug: str  # id it would get when indexed (for matching with Document)
    # status — None if the document is not in the DB yet (not indexed).
    # Otherwise processing/ready/failed.
    status: str | None
    pinned: bool
    # Human-readable failure reason (only when status='failed').
    error: str | None = None
    # Current processing stage (only when status='processing'), e.g.
    # "popis obrázků: strana 12/47". Ephemeral, from backend.core.progress.
    progress: str | None = None


class LibraryFolder(BaseModel):
    """A folder in the library tree. May contain subfolders and PDFs."""

    name: str
    path: str  # absolute path to the folder
    folders: list["LibraryFolder"]
    files: list[LibraryFile]


class OrphanDocument(BaseModel):
    """A DB document whose PDF disappeared from the library folder.

    The user may have deleted or renamed the file. The UI shows them in a
    separate "orphans" section with "This is a rename" and (later) "Remove"
    buttons.
    """

    slug: str
    title: str
    status: str


class LibraryResponse(BaseModel):
    """Full GET /api/library response: tree + orphan documents."""

    tree: LibraryFolder
    orphans: list[OrphanDocument]


class ScanSummary(BaseModel):
    """POST /api/library/scan response: how many PDFs were found and handled."""

    created: int  # new documents sent to the pipeline
    already_indexed: int  # PDFs that already have a DB record
    # New PDFs with a ready index in .search_index (someone already indexed
    # this folder, e.g. a colleague on a network drive) — ready at once, free.
    adopted: int = 0
    # Files skipped because of name collisions (several PDFs map to one id).
    # We leave them alone so one does not overwrite another — ask the user
    # to rename.
    duplicates: list[str] = []
    # Ready indexes NOT adopted because of the public build page limit
    # (see backend/core/limits.py) — registered as pending.
    limit_skipped: int = 0
