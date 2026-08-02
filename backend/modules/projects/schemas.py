"""Pydantic schemas of the projects module (project archive)."""

from pydantic import BaseModel, ConfigDict


class ProjectDocumentOut(BaseModel):
    """An archive document in API responses."""

    model_config = ConfigDict(from_attributes=True)

    slug: str
    project: str
    relative_path: str
    page_count: int
    status: str
    error: str | None = None
    pinned: bool = False
    # Current processing stage (only when status='processing'), ephemeral —
    # filled from backend.core.progress, not stored in the DB.
    progress: str | None = None


class ProjectGroup(BaseModel):
    """One project: folder name + its documents."""

    name: str
    documents: list[ProjectDocumentOut]


class ArchiveResponse(BaseModel):
    """GET /projects response: archive folders + documents by project."""

    paths: list[str]
    projects: list[ProjectGroup]


class ArchiveScanSummary(BaseModel):
    """POST /projects/scan result."""

    found: int  # total PDFs in the project folders (without duplicates)
    new: int  # new records added
    missing: int  # removed: files no longer on disk (indexes cleaned up)
    changed: int = 0  # replaced PDFs (new content) — reset to pending
    duplicates: list[str]  # same-named files (slug taken) — not indexed
    errors: list[str]  # files that could not be opened as PDFs
    unavailable: list[str]  # unavailable folders (network drive) — cleanup skipped
