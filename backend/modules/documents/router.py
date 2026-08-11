"""HTTP endpoints of the documents module."""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.core.database import get_session
from backend.modules.documents import service
from backend.modules.documents.schemas import DocumentResponse
from backend.modules.settings import service as settings_service


router = APIRouter()


class RelinkRequest(BaseModel):
    """Request: "document old_slug was renamed; the new name gives new_slug"."""

    old_slug: str
    new_slug: str


@router.get("/documents", response_model=list[DocumentResponse])
def list_documents(db: Session = Depends(get_session)) -> list:
    """All documents in the library."""
    return service.list_documents(db)


@router.post("/documents/{slug}/reindex", response_model=DocumentResponse)
def reindex_document(
    slug: str,
    request: Request,
    db: Session = Depends(get_session),
) -> DocumentResponse:
    """Full re-processing: drop old chunks, run the pipeline again."""
    paths = [Path(p) for p in settings_service.get_library_paths(db)]
    if not paths:
        raise HTTPException(status_code=400, detail="No library folder is set")
    executor = request.app.state.executor
    try:
        return service.reindex_document(db, slug, paths, executor)
    except service.DocumentBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/documents/{slug}/stop")
def stop_document(slug: str, db: Session = Depends(get_session)) -> dict:
    """⏹: stop indexing this document (queued — immediately, running —
    at the nearest safe point). Checkpoints survive, resuming is free."""
    service.stop_document(db, slug)
    return {"status": "ok"}


@router.delete("/documents/{slug}")
def delete_document(slug: str, db: Session = Depends(get_session)) -> dict:
    """Remove the document from the index. The PDF stays in place."""
    paths = [Path(p) for p in settings_service.get_library_paths(db)]
    try:
        service.delete_document(db, slug, paths)
    except service.DocumentBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "ok"}


@router.post("/documents/{slug}/pin", response_model=DocumentResponse)
def toggle_pin(slug: str, db: Session = Depends(get_session)) -> DocumentResponse:
    """Toggle the document pin."""
    try:
        return service.toggle_pin(db, slug)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/documents/relink", response_model=DocumentResponse)
def relink_document(
    body: RelinkRequest,
    db: Session = Depends(get_session),
) -> DocumentResponse:
    """Move the index from the old slug to the new one — for renamed files."""
    paths = [Path(p) for p in settings_service.get_library_paths(db)]
    try:
        return service.relink_document(db, body.old_slug, body.new_slug, paths)
    except service.DocumentBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
