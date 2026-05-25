"""Pydantic-схемы для эндпоинтов модуля settings."""

from pydantic import BaseModel


class LibraryPathResponse(BaseModel):
    """Текущий путь к папке библиотеки. None — путь не задан."""

    path: str | None


class LibraryPathRequest(BaseModel):
    """Установить путь к папке библиотеки."""

    path: str
