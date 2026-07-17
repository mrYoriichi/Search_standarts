"""HTTP-эндпоинты модуля library."""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.core.database import get_session
from backend.modules.library import service
from backend.modules.library.schemas import LibraryResponse, ScanSummary
from backend.modules.settings import service as settings_service


router = APIRouter()


class OpenFileRequest(BaseModel):
    """Запрос на открытие файла из библиотеки."""

    path: str


def _library_paths(db: Session) -> list[Path]:
    """Список папок библиотеки как Path. HTTP 400, если ни одной не задано."""
    paths = settings_service.get_library_paths(db)
    if not paths:
        raise HTTPException(status_code=400, detail="Папка библиотеки не задана")
    return [Path(p) for p in paths]


@router.get("/library", response_model=LibraryResponse)
def get_library(db: Session = Depends(get_session)) -> LibraryResponse:
    """Возвращает дерево папок библиотеки + список висячих документов."""
    return service.build_library_response(_library_paths(db), db)


@router.post("/library/open")
def open_library_file(
    body: OpenFileRequest,
    db: Session = Depends(get_session),
) -> dict:
    """Открывает PDF из библиотеки в системном просмотрщике."""
    try:
        service.open_file(_library_paths(db), body.path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ok"}


@router.get("/library/shared", response_model=LibraryResponse)
def get_shared_library(db: Session = Depends(get_session)) -> LibraryResponse:
    """Дерево общей базы (read-only). Статус «ready» — по наличию индексов."""
    shared = settings_service.get_shared_library_path(db)
    if shared is None:
        raise HTTPException(status_code=400, detail="Папка общей базы не задана")
    pdfs_root = Path(shared) / "pdfs"
    if not pdfs_root.exists():
        raise HTTPException(
            status_code=400, detail="В папке общей базы нет подпапки 'pdfs'"
        )
    return service.build_shared_library_response(
        pdfs_root,
        Path(shared) / "raw_data",
        settings_service.get_shared_pinned_slugs(db),
    )


@router.post("/library/shared/{slug}/pin")
def pin_shared_document(slug: str, db: Session = Depends(get_session)) -> dict:
    """Переключает закрепление документа общей базы (пины в настройках)."""
    return {"pinned": settings_service.toggle_shared_pin(db, slug)}


@router.post("/library/shared/open")
def open_shared_file(
    body: OpenFileRequest,
    db: Session = Depends(get_session),
) -> dict:
    """Открывает PDF из общей базы в системном просмотрщике."""
    shared = settings_service.get_shared_library_path(db)
    if shared is None:
        raise HTTPException(status_code=400, detail="Папка общей базы не задана")
    try:
        service.open_file([Path(shared) / "pdfs"], body.path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ok"}


@router.post("/library/scan", response_model=ScanSummary)
def scan_library(
    db: Session = Depends(get_session),
) -> ScanSummary:
    """Сканирует папки библиотеки: новые PDF регистрирует как pending (čeká)."""
    return service.scan_library(_library_paths(db), db)


@router.post("/library/index")
def index_library(
    request: Request,
    db: Session = Depends(get_session),
) -> dict:
    """Отправляет обнаруженные (pending) PDF в обработку — платный шаг."""
    executor = request.app.state.executor
    started = service.start_indexing(_library_paths(db), db, executor)
    return {"started": started}


@router.get("/library/pdf/{slug}")
def get_pdf(slug: str, db: Session = Depends(get_session)) -> FileResponse:
    """Отдаёт PDF по slug — для просмотра в браузере. Ищет во всех пулах.

    Папка юзера → общая база (`<shared>/pdfs`) → архив проектов — источник в
    ответе может быть из любого пула. Браузер сам поддерживает `#page=N`.
    """
    library_paths = settings_service.get_library_paths(db)
    pdf_path = (
        service.find_pdf_by_slug([Path(p) for p in library_paths], slug)
        if library_paths
        else None
    )
    if pdf_path is None:
        shared = settings_service.get_shared_library_path(db)
        if shared is not None:
            pdf_path = service.find_pdf_by_slug(Path(shared) / "pdfs", slug)
    if pdf_path is None:
        # Архив проектов: точный путь знает БД (slug уникален по архиву).
        from backend.modules.projects.models import ProjectDocument
        from sqlalchemy import select

        projects_path = settings_service.get_projects_path(db)
        pdoc = db.scalar(select(ProjectDocument).where(ProjectDocument.slug == slug))
        if projects_path and pdoc is not None:
            candidate = Path(projects_path) / pdoc.relative_path
            if candidate.exists():
                pdf_path = candidate
    if pdf_path is None:
        raise HTTPException(status_code=404, detail=f"PDF для slug={slug} не найден")
    return FileResponse(pdf_path, media_type="application/pdf")
