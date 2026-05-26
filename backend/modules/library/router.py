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


@router.get("/library", response_model=LibraryResponse)
def get_library(db: Session = Depends(get_session)) -> LibraryResponse:
    """Возвращает дерево папки библиотеки + список висячих документов."""
    library_path = settings_service.get_library_path(db)
    if library_path is None:
        raise HTTPException(
            status_code=400, detail="Папка библиотеки не задана"
        )
    return service.build_library_response(Path(library_path), db)


@router.post("/library/open")
def open_library_file(
    body: OpenFileRequest,
    db: Session = Depends(get_session),
) -> dict:
    """Открывает PDF из библиотеки в системном просмотрщике."""
    library_path = settings_service.get_library_path(db)
    if library_path is None:
        raise HTTPException(
            status_code=400, detail="Папка библиотеки не задана"
        )
    try:
        service.open_file(Path(library_path), body.path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ok"}


@router.post("/library/scan", response_model=ScanSummary)
def scan_library(
    request: Request,
    db: Session = Depends(get_session),
) -> ScanSummary:
    """Сканирует папку библиотеки: новые PDF отправляет в pipeline в фон."""
    library_path = settings_service.get_library_path(db)
    if library_path is None:
        raise HTTPException(status_code=400, detail="Папка библиотеки не задана")
    executor = request.app.state.executor
    return service.scan_library(Path(library_path), db, executor)


@router.get("/library/pdf/{slug}")
def get_pdf(slug: str, db: Session = Depends(get_session)) -> FileResponse:
    """Отдаёт PDF из папки библиотеки по slug — для просмотра в браузере.

    Браузер сам поддерживает фрагмент URL `#page=N` — фронт строит такую
    ссылку и юзер открывает PDF сразу на нужной странице.
    """
    library_path = settings_service.get_library_path(db)
    if library_path is None:
        raise HTTPException(status_code=400, detail="Папка библиотеки не задана")
    pdf_path = service.find_pdf_by_slug(Path(library_path), slug)
    if pdf_path is None:
        raise HTTPException(
            status_code=404, detail=f"PDF для slug={slug} не найден в библиотеке"
        )
    return FileResponse(pdf_path, media_type="application/pdf")
