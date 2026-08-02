"""HTTP-эндпоинты модуля documents."""

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
    """Запрос: «документ old_slug — это переименование, новое имя даёт new_slug»."""

    old_slug: str
    new_slug: str


@router.get("/documents", response_model=list[DocumentResponse])
def list_documents(db: Session = Depends(get_session)) -> list:
    """Список всех документов в библиотеке."""
    return service.list_documents(db)


@router.post("/documents/{slug}/reindex", response_model=DocumentResponse)
def reindex_document(
    slug: str,
    request: Request,
    db: Session = Depends(get_session),
) -> DocumentResponse:
    """Полная переобработка документа: старые чанки удаляем, pipeline запускаем заново."""
    paths = [Path(p) for p in settings_service.get_library_paths(db)]
    if not paths:
        raise HTTPException(status_code=400, detail="Папка библиотеки не задана")
    executor = request.app.state.executor
    try:
        return service.reindex_document(db, slug, paths, executor)
    except service.DocumentBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/documents/{slug}")
def delete_document(slug: str, db: Session = Depends(get_session)) -> dict:
    """Убирает документ из индекса. Файл PDF в библиотеке остаётся на месте."""
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
    """Переключает закреплённость документа."""
    try:
        return service.toggle_pin(db, slug)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/documents/relink", response_model=DocumentResponse)
def relink_document(
    body: RelinkRequest,
    db: Session = Depends(get_session),
) -> DocumentResponse:
    """Переносит индекс со старого slug на новый — для переименования файла."""
    paths = [Path(p) for p in settings_service.get_library_paths(db)]
    try:
        return service.relink_document(db, body.old_slug, body.new_slug, paths)
    except service.DocumentBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
