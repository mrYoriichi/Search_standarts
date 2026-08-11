"""HTTP endpoints of the library module."""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.core import page_stats
from backend.core.database import get_session
from backend.core.ui_messages import msg
from backend.modules.library import service
from backend.modules.library.schemas import LibraryResponse, LibraryStats, ScanSummary
from backend.modules.settings import service as settings_service


router = APIRouter()


class OpenFileRequest(BaseModel):
    """Request to open a file from the library."""

    path: str


def _library_paths(db: Session) -> list[Path]:
    """Library folders as Path objects. HTTP 400 if none is configured."""
    paths = settings_service.get_library_paths(db)
    if not paths:
        raise HTTPException(status_code=400, detail=msg("lib.no_library_path"))
    return [Path(p) for p in paths]


@router.get("/library", response_model=LibraryResponse)
def get_library(db: Session = Depends(get_session)) -> LibraryResponse:
    """Return the library folder tree + the list of orphan documents."""
    return service.build_library_response(_library_paths(db), db)


@router.post("/library/open")
def open_library_file(
    body: OpenFileRequest,
    db: Session = Depends(get_session),
) -> dict:
    """Open a library PDF in the system viewer."""
    try:
        service.open_file(_library_paths(db), body.path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ok"}


@router.post("/library/scan", response_model=ScanSummary)
def scan_library(
    db: Session = Depends(get_session),
) -> ScanSummary:
    """Scan the library folders: register new PDFs as pending (čeká)."""
    return service.scan_library(_library_paths(db), db)


@router.post("/library/index")
def index_library(
    request: Request,
    db: Session = Depends(get_session),
) -> dict:
    """Send discovered (pending) PDFs to processing — the paid step."""
    executor = request.app.state.executor
    started, locked = service.start_indexing(_library_paths(db), db, executor)
    return {"started": started, "locked": locked}


@router.post("/library/index/{slug}")
def index_library_document(
    slug: str,
    request: Request,
    db: Session = Depends(get_session),
) -> dict:
    """Send ONE pending document to processing (the ▶ button on a file)."""
    executor = request.app.state.executor
    started, locked = service.start_indexing(
        _library_paths(db), db, executor, only_slug=slug
    )
    return {"started": started, "locked": locked}


@router.get("/library/stats", response_model=LibraryStats)
def library_stats(db: Session = Depends(get_session)) -> LibraryStats:
    """Ready-page counters shown in the library and archive headers."""
    library = page_stats.library_pages(db)
    archive = page_stats.archive_pages(db)
    return LibraryStats(
        pages_library=library,
        pages_archive=archive,
        pages_total=library + archive,
    )


@router.get("/library/pdf/{slug}")
def get_pdf(slug: str, db: Session = Depends(get_session)) -> FileResponse:
    """Serve a PDF by slug — for viewing in the browser. Looks in all pools.

    Library folders -> project archive — the source in an answer may come
    from any pool. The browser natively supports `#page=N`.
    """
    pdf_path = service.resolve_pdf_by_slug(db, slug)
    if pdf_path is None:
        raise HTTPException(status_code=404, detail=msg("lib.pdf_not_found", slug=slug))
    return FileResponse(pdf_path, media_type="application/pdf")
