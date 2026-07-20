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
    expand: bool = Field(
        default=True,
        description="Расширять ли запрос через LLM (диакритика/синонимы) перед поиском.",
    )
    strong: bool = Field(
        default=False,
        description="Сильный поиск: приложить снимки страниц топ-источников "
        "к отвечающей LLM (дороже и медленнее, для тяжёлых вопросов).",
    )


class UsedChunk(BaseModel):
    """Фрагмент, на который модель реально опиралась — с полным текстом.

    Нужен для отчётов «Nahlásit» (F7): по жалобе видно, что читала модель."""

    chunk_id: str
    document: str
    section: str
    pages: list[int]
    text: str


class FlagRequest(BaseModel):
    """Пометка «Nahlásit»: юзер сообщает, что ответ неверный/не нашёлся.

    Текст шлём прямо с фронта (он уже показан юзеру) — так не нужно лезть в
    QueryLog и менять его схему. note — необязательная заметка «почему не так».
    used_chunks — фрагменты, которые модель использовала (с текстом)."""

    question: str = Field(..., min_length=1)
    answer: str
    answer_model: str | None = None
    note: str | None = None
    used_chunks: list[UsedChunk] = Field(default_factory=list)


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
    # Использованные фрагменты с текстом — фронт хранит и возвращает при «Nahlásit».
    used_chunks: list[UsedChunk]
    query_log_id: int
    search_query: str  # расширенный запрос, которым реально искали (показываем юзеру)
    answer_model: str  # модель, сгенерировавшая ответ
    answer_ms: int  # время генерации ответа, мс (для сравнения моделей)
