"""HTTP-эндпоинты модуля settings."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.core.database import get_session
from backend.modules.settings import service
from backend.modules.settings.schemas import LibraryPathRequest, LibraryPathResponse


router = APIRouter()


@router.get("/settings/library", response_model=LibraryPathResponse)
def get_library_path(db: Session = Depends(get_session)) -> LibraryPathResponse:
    """Возвращает текущий путь к папке библиотеки. None — путь не задан."""
    return LibraryPathResponse(path=service.get_library_path(db))


@router.put("/settings/library", response_model=LibraryPathResponse)
def set_library_path(
    body: LibraryPathRequest,
    db: Session = Depends(get_session),
) -> LibraryPathResponse:
    """Сохраняет путь к папке библиотеки. Валидирует, что папка существует."""
    try:
        saved = service.set_library_path(db, body.path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return LibraryPathResponse(path=saved)
