"""Pydantic schemas for the settings endpoints."""

from typing import Literal

from pydantic import BaseModel


class LibraryPathResponse(BaseModel):
    """Current library folder path. None — not set."""

    path: str | None


class LibraryPathRequest(BaseModel):
    """Set the library folder path."""

    path: str


class LibraryPathsResponse(BaseModel):
    """The list of library folders."""

    paths: list[str]


class LibraryPathUpdate(BaseModel):
    """Replace a folder in the list: old path → new (edit)."""

    old_path: str
    new_path: str


class OpenAIKeyStatus(BaseModel):
    """OpenAI key status. The full key never leaves — only the tail."""

    is_set: bool
    masked: str | None


class OpenAIKeyRequest(BaseModel):
    """Set the OpenAI key."""

    key: str


class VisionModelSetting(BaseModel):
    """Vision model for document processing (the cost lever)."""

    model: str


class DescribeImagesSetting(BaseModel):
    """Vision description toggle. False = "No LLM" (free)."""

    enabled: bool


class UiLanguageSetting(BaseModel):
    """Interface language — the backend uses it for error texts."""

    language: Literal["cs", "en", "de"]


class AnswerLanguageSetting(BaseModel):
    """LLM answer language — a profile setting, independent of the UI."""

    language: Literal["cs", "en", "de"]
