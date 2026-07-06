"""HTTP-эндпоинты модуля projects (архив проектов)."""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.core.database import get_session
from backend.modules.projects import service
from backend.modules.projects.schemas import ArchiveResponse, ArchiveScanSummary
from backend.modules.settings import service as settings_service


router = APIRouter()


@router.get("/projects", response_model=ArchiveResponse)
def get_archive(db: Session = Depends(get_session)) -> ArchiveResponse:
    """Документы архива по проектам + текущий путь к папке."""
    return service.build_archive_response(
        db, settings_service.get_projects_path(db)
    )


@router.post("/projects/scan", response_model=ArchiveScanSummary)
def scan_archive(db: Session = Depends(get_session)) -> ArchiveScanSummary:
    """Сканирует папку архива: классифицирует PDF и заносит новые в БД.

    Индексация (пайплайн) — этап 2, пока новые документы остаются "pending".
    """
    projects_path = settings_service.get_projects_path(db)
    if projects_path is None:
        raise HTTPException(status_code=400, detail="Папка архива не задана")
    return service.sync_archive(db, Path(projects_path))
