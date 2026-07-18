"""HTTP-эндпоинты модуля projects (архив проектов)."""

import threading
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.database import get_session
from backend.modules.projects import service
from backend.modules.projects.models import ProjectDocument
from backend.modules.projects.pipeline import run_project_pipeline
from backend.modules.projects.schemas import (
    ArchiveResponse,
    ArchiveScanSummary,
    ProjectDocumentOut,
)
from backend.modules.settings import service as settings_service


router = APIRouter()

# Сериализует POST /projects/index (даблклик) — см. комментарий в index_archive.
_index_archive_lock = threading.Lock()


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


@router.post("/projects/index")
def index_archive(
    request: Request,
    db: Session = Depends(get_session),
) -> dict:
    """Отправляет обнаруженные (pending) документы архива в обработку.

    Статус сразу переводим в processing — повторный клик не отправит те же
    документы второй раз, а после падения их подхватит возобновление на старте.
    Папку каждого документа находим по наличию его файла на диске.
    """
    paths = _projects_paths(db)
    executor = request.app.state.executor
    # Под замком: два одновременных клика иначе прочитают одни и те же
    # pending до чужого commit — двойная оплата vision.
    with _index_archive_lock:
        pending = db.scalars(
            select(ProjectDocument).where(ProjectDocument.status == "pending")
        ).all()

        submitted = 0
        for doc in pending:
            root = service.resolve_project_root(paths, doc.relative_path)
            if root is None:
                continue  # файл не найден ни в одной папке — пропускаем
            doc.status = "processing"
            db.commit()
            executor.submit(
                run_project_pipeline, doc.slug, str(root / doc.relative_path)
            )
            submitted += 1

    return {"started": submitted}
