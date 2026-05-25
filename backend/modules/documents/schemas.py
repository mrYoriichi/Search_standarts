"""Pydantic-схемы для эндпоинтов модуля documents."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class DocumentResponse(BaseModel):
    """Один документ в ответе API — то, что видит фронт в списке библиотеки."""

    # from_attributes=True позволяет Pydantic читать поля прямо из ORM-модели,
    # без ручного маппинга. То есть можно вернуть Document(...) — FastAPI сам сериализует.
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    title: str
    status: str
    error_message: str | None = None
    pinned: bool
    created_at: datetime


class UploadItem(BaseModel):
    """Результат загрузки одного файла в пачке."""

    slug: str
    title: str
    # created — новая запись, pipeline запущен.
    # skipped — документ с таким slug уже есть в БД, оставили как был.
    action: Literal["created", "skipped"]


class UploadResponse(BaseModel):
    """Ответ на POST /api/documents с пачкой файлов."""

    items: list[UploadItem]
