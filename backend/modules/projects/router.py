"""HTTP endpoints of the projects module (project archive)."""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from backend.core.database import get_session
from backend.core.ui_messages import msg
from backend.modules.projects import service
from backend.modules.projects.schemas import (
    ArchiveResponse,
    ArchiveScanSummary,
    ProjectDocumentOut,
)
from backend.modules.settings import service as settings_service


router = APIRouter()


def _projects_paths(db: Session) -> list[Path]:
    """Archive folders as Path objects. HTTP 400 if none is configured."""
    paths = settings_service.get_projects_paths(db)
    if not paths:
        raise HTTPException(status_code=400, detail=msg("projects.no_archive_path"))
    return [Path(p) for p in paths]


@router.get("/projects", response_model=ArchiveResponse)
def get_archive(db: Session = Depends(get_session)) -> ArchiveResponse:
    """Archive documents grouped by project + the current folders."""
    return service.build_archive_response(db, settings_service.get_projects_paths(db))


@router.post("/projects/scan", response_model=ArchiveScanSummary)
def scan_archive(
    db: Session = Depends(get_session),
) -> ArchiveScanSummary:
    """Scan the archive folders: new PDFs get the pending status (čeká).

    Scanning is free, indexing is paid (vision) — launched by a separate
    POST /projects/index so the user sees the list BEFORE spending money.
    """
    return service.sync_archive(db, _projects_paths(db))


@router.post("/projects/{slug}/pin", response_model=ProjectDocumentOut)
def toggle_pin(slug: str, db: Session = Depends(get_session)) -> ProjectDocumentOut:
    """Toggle the pinned state of an archive document."""
    try:
        return service.toggle_pin(db, slug)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/projects/{slug}/reindex", response_model=ProjectDocumentOut)
def reindex_document(
    slug: str,
    request: Request,
    db: Session = Depends(get_session),
) -> ProjectDocumentOut:
    """Full reprocessing of an archive document: artifacts removed, pipeline rerun."""
    try:
        return service.reindex_document(
            db, slug, _projects_paths(db), request.app.state.executor
        )
    except service.DocumentBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/projects/index")
def index_archive(
    request: Request,
    db: Session = Depends(get_session),
) -> dict:
    """Send discovered (pending) archive documents to processing."""
    submitted, locked = service.start_archive_indexing(
        db, _projects_paths(db), request.app.state.executor
    )
    return {"started": submitted, "locked": locked}


@router.post("/projects/index/{slug}")
def index_archive_document(
    slug: str,
    request: Request,
    db: Session = Depends(get_session),
) -> dict:
    """Send ONE pending archive document to processing (the ▶ button)."""
    submitted, locked = service.start_archive_indexing(
        db, _projects_paths(db), request.app.state.executor, only_slug=slug
    )
    return {"started": submitted, "locked": locked}
