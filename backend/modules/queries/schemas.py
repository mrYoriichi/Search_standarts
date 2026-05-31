"""Pydantic-схемы для эндпоинта «Вопрос → Ответ».

Описывают форму JSON на входе (что фронт шлёт) и на выходе (что вернём).
FastAPI сам валидирует входящие данные по этим схемам и строит /docs.
"""

from typing import Literal

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    """Запрос от фронта: вопрос + опциональный фильтр по документам + режим поиска."""

    question: str = Field(..., min_length=1, description="Текст вопроса пользователя")
    document_ids: list[str] | None = Field(
        default=None,
        description="Slug'и документов для фильтра. None = искать по всей библиотеке.",
    )
    mode: Literal["hybrid", "vector", "keyword"] = Field(
        default="hybrid",
        description="Режим поиска: hybrid (7 вектор + 7 BM25), vector (топ-20 вектор), keyword (топ-10 BM25).",
    )
    answer_model: Literal["gpt-5.4-mini", "gpt-5.5"] = Field(
        default="gpt-5.4-mini",
        description="Модель генерации ответа.",
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
    related_sources: list[Source]  # релевантные, но не использованные напрямую
    query_log_id: int
    search_query: str  # расширенный запрос, которым реально искали (показываем юзеру)
    answer_model: str  # модель, сгенерировавшая ответ
    answer_ms: int     # время генерации ответа, мс (для сравнения моделей)
