"""Pydantic-схемы для эндпоинта «Вопрос → Ответ».

Описывают форму JSON на входе (что фронт шлёт) и на выходе (что вернём).
FastAPI сам валидирует входящие данные по этим схемам и строит /docs.
"""

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    """Запрос от фронта: вопрос + опциональный фильтр по документам."""

    question: str = Field(..., min_length=1, description="Текст вопроса пользователя")
    document_ids: list[str] | None = Field(
        default=None,
        description="Slug'и документов для фильтра. None = искать по всей библиотеке.",
    )


class Source(BaseModel):
    """Один источник: на какой документ/раздел/страницы опирался ответ."""

    document: str
    slug: str  # id документа — нужно фронту, чтобы построить ссылку на PDF
    section: str
    pages: list[int]


class AskResponse(BaseModel):
    """Ответ эндпоинта: текст + источники + id записи в QueryLog."""

    answer: str
    sources: list[Source]
    query_log_id: int
