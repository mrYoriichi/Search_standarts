"""HTTP-эндпоинты модуля settings."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.core.database import get_session
from backend.modules.settings import service
from backend.modules.settings.schemas import (
    LibraryPathRequest,
    LibraryPathResponse,
    LibraryPathsResponse,
    LibraryPathUpdate,
    OpenAIKeyRequest,
    OpenAIKeyStatus,
    VisionModelSetting,
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


@router.get("/settings/libraries", response_model=LibraryPathsResponse)
def get_library_paths(db: Session = Depends(get_session)) -> LibraryPathsResponse:
    """Список папок библиотеки (мигрирует со старого одиночного пути)."""
    return LibraryPathsResponse(paths=service.get_library_paths(db))


@router.post("/settings/libraries", response_model=LibraryPathsResponse)
def add_library_path(
    body: LibraryPathRequest,
    db: Session = Depends(get_session),
) -> LibraryPathsResponse:
    """Добавляет папку в список библиотеки. 400, если папки нет на диске."""
    try:
        paths = service.add_library_path(db, body.path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return LibraryPathsResponse(paths=paths)


@router.put("/settings/libraries", response_model=LibraryPathsResponse)
def update_library_path(
    body: LibraryPathUpdate,
    db: Session = Depends(get_session),
) -> LibraryPathsResponse:
    """Правит путь папки в списке. 400, если новой папки нет на диске."""
    try:
        paths = service.update_library_path(db, body.old_path, body.new_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return LibraryPathsResponse(paths=paths)


@router.delete("/settings/libraries", response_model=LibraryPathsResponse)
def remove_library_path(
    body: LibraryPathRequest,
    db: Session = Depends(get_session),
) -> LibraryPathsResponse:
    """Убирает папку из списка библиотеки. Индексы на диске не трогаем."""
    paths = service.remove_library_path(db, body.path)
    return LibraryPathsResponse(paths=paths)


@router.get("/settings/shared-library", response_model=LibraryPathResponse)
def get_shared_library_path(
    db: Session = Depends(get_session),
) -> LibraryPathResponse:
    """Возвращает путь к папке общей базы. None — путь не задан."""
    return LibraryPathResponse(path=service.get_shared_library_path(db))


@router.put("/settings/shared-library", response_model=LibraryPathResponse)
def set_shared_library_path(
    body: LibraryPathRequest,
    db: Session = Depends(get_session),
) -> LibraryPathResponse:
    """Сохраняет путь к папке общей базы. Валидирует, что папка существует."""
    try:
        saved = service.set_shared_library_path(db, body.path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return LibraryPathResponse(path=saved)


@router.get("/settings/projects", response_model=LibraryPathResponse)
def get_projects_path(db: Session = Depends(get_session)) -> LibraryPathResponse:
    """Возвращает путь к папке архива проектов. None — путь не задан."""
    return LibraryPathResponse(path=service.get_projects_path(db))


@router.put("/settings/projects", response_model=LibraryPathResponse)
def set_projects_path(
    body: LibraryPathRequest,
    db: Session = Depends(get_session),
) -> LibraryPathResponse:
    """Сохраняет путь к папке архива проектов. Валидирует, что папка существует."""
    try:
        saved = service.set_projects_path(db, body.path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return LibraryPathResponse(path=saved)


@router.get("/settings/vision-model", response_model=VisionModelSetting)
def get_vision_model(db: Session = Depends(get_session)) -> VisionModelSetting:
    """Текущая vision-модель для обработки документов."""
    return VisionModelSetting(model=service.get_vision_model(db))


@router.put("/settings/vision-model", response_model=VisionModelSetting)
def set_vision_model(
    body: VisionModelSetting,
    db: Session = Depends(get_session),
) -> VisionModelSetting:
    """Сохраняет выбор vision-модели. 400 на неизвестную модель."""
    try:
        saved = service.set_vision_model(db, body.model)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return VisionModelSetting(model=saved)


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
