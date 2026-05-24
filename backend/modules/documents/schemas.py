"""Pydantic-схемы для эндпоинтов модуля documents."""

from datetime import datetime

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
    created_at: datetime
