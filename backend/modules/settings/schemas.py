"""Pydantic-схемы для эндпоинтов модуля settings."""

from pydantic import BaseModel


class LibraryPathResponse(BaseModel):
    """Текущий путь к папке библиотеки. None — путь не задан."""

    path: str | None


class LibraryPathRequest(BaseModel):
    """Установить путь к папке библиотеки."""

    path: str


class LibraryPathsResponse(BaseModel):
    """Список папок библиотеки."""

    paths: list[str]


class LibraryPathUpdate(BaseModel):
    """Заменить папку в списке: старый путь → новый (правка)."""

    old_path: str
    new_path: str


class OpenAIKeyStatus(BaseModel):
    """Статус ключа OpenAI. Полный ключ наружу не отдаём — только хвост."""

    is_set: bool
    masked: str | None


class OpenAIKeyRequest(BaseModel):
    """Установить ключ OpenAI."""

    key: str


class VisionModelSetting(BaseModel):
    """Vision-модель для обработки документов (рычаг стоимости)."""

    model: str


class DescribeImagesSetting(BaseModel):
    """Тумблер описания картинок vision. False = «Без LLM» (бесплатно)."""

    enabled: bool
