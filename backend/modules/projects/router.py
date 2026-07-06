"""HTTP-эндпоинты модуля projects (архив проектов)."""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.database import get_session
from backend.modules.projects import service
from backend.modules.projects.models import ProjectDocument
from backend.modules.projects.pipeline import run_project_pipeline
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
def scan_archive(
    request: Request,
    db: Session = Depends(get_session),
) -> ArchiveScanSummary:
    """Сканирует папку архива и отправляет необработанные PDF в пайплайн.

    Обработка идёт в фоне (ThreadPoolExecutor, как у норм): каждый документ
    сам переводит свой статус pending → processing → ready/error.
    """
    projects_path = settings_service.get_projects_path(db)
    if projects_path is None:
        raise HTTPException(status_code=400, detail="Папка архива не задана")
    root = Path(projects_path)
    summary = service.sync_archive(db, root)

    executor = request.app.state.executor
    pending = db.scalars(
        select(ProjectDocument).where(ProjectDocument.status == "pending")
    ).all()
    for doc in pending:
        executor.submit(run_project_pipeline, doc.slug, str(root / doc.relative_path))

    return summary
