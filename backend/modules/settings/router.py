"""HTTP-эндпоинты модуля settings."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.core.database import get_session
from backend.modules.settings import service
from backend.modules.settings.schemas import (
    LibraryPathRequest,
    LibraryPathResponse,
    OpenAIKeyRequest,
    OpenAIKeyStatus,
)


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


@router.get("/settings/openai-key", response_model=OpenAIKeyStatus)
def get_openai_key(db: Session = Depends(get_session)) -> OpenAIKeyStatus:
    """Статус ключа OpenAI: задан ли он и его маскированный хвост."""
    key = service.get_openai_key(db)
    return OpenAIKeyStatus(
        is_set=bool(key),
        masked=service.mask_key(key) if key else None,
    )


@router.put("/settings/openai-key", response_model=OpenAIKeyStatus)
def set_openai_key(
    body: OpenAIKeyRequest,
    db: Session = Depends(get_session),
) -> OpenAIKeyStatus:
    """Сохраняет ключ OpenAI. Проверяет формат, кладёт в БД и в окружение."""
    try:
        saved = service.set_openai_key(db, body.key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return OpenAIKeyStatus(is_set=True, masked=service.mask_key(saved))
