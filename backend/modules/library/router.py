"""HTTP-эндпоинты модуля library."""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.core.database import get_session
from backend.modules.library import service
from backend.modules.library.schemas import LibraryFolder
from backend.modules.settings import service as settings_service


router = APIRouter()


class OpenFileRequest(BaseModel):
    """Запрос на открытие файла из библиотеки."""

    path: str


@router.get("/library", response_model=LibraryFolder)
def get_library(db: Session = Depends(get_session)) -> LibraryFolder:
    """Возвращает дерево папки библиотеки с PDF-файлами и их статусом."""
    library_path = settings_service.get_library_path(db)
    if library_path is None:
        raise HTTPException(
            status_code=400, detail="Папка библиотеки не задана"
        )
    return service.build_tree(Path(library_path), db)


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
