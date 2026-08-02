"""HTTP-эндпоинты модуля projects (архив проектов)."""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from backend.core.database import get_session
from backend.modules.projects import service
from backend.modules.projects.schemas import (
    ArchiveResponse,
    ArchiveScanSummary,
    ProjectDocumentOut,
)
from backend.modules.settings import service as settings_service


router = APIRouter()


def _projects_paths(db: Session) -> list[Path]:
    """Список папок архива как Path. HTTP 400, если ни одной не задано."""
    paths = settings_service.get_projects_paths(db)
    if not paths:
        raise HTTPException(status_code=400, detail="Папка архива не задана")
    return [Path(p) for p in paths]


@router.get("/projects", response_model=ArchiveResponse)
def get_archive(db: Session = Depends(get_session)) -> ArchiveResponse:
    """Документы архива по проектам + текущие папки."""
    return service.build_archive_response(db, settings_service.get_projects_paths(db))


@router.post("/projects/scan", response_model=ArchiveScanSummary)
def scan_archive(
    db: Session = Depends(get_session),
) -> ArchiveScanSummary:
    """Сканирует папки архива: новые PDF получают статус pending (čeká).

    Скан бесплатный, индексация платная (vision) — запускается отдельным
    POST /projects/index, чтобы юзер видел список ДО траты денег.
    """
    return service.sync_archive(db, _projects_paths(db))


@router.post("/projects/{slug}/pin", response_model=ProjectDocumentOut)
def toggle_pin(slug: str, db: Session = Depends(get_session)) -> ProjectDocumentOut:
    """Переключает закреплённость документа архива."""
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
    """Полная переобработка документа архива: артефакты удаляем, pipeline заново."""
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
    """Отправляет обнаруженные (pending) документы архива в обработку."""
    submitted, over_limit = service.start_archive_indexing(
        db, _projects_paths(db), request.app.state.executor
    )
    return {"started": submitted, "over_limit": over_limit}
