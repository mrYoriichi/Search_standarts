"""Pydantic-схемы модуля projects (архив проектов)."""

from pydantic import BaseModel, ConfigDict


class ProjectDocumentOut(BaseModel):
    """Документ архива в ответах API."""

    model_config = ConfigDict(from_attributes=True)

    slug: str
    project: str
    relative_path: str
    page_count: int
    status: str
    error: str | None = None
    pinned: bool = False
    # Текущая стадия обработки (только при status='processing'), эфемерное —
    # заполняется из backend.core.progress, в БД его нет.
    progress: str | None = None


class ProjectGroup(BaseModel):
    """Один проект: имя папки + его документы."""

    name: str
    documents: list[ProjectDocumentOut]


class ArchiveResponse(BaseModel):
    """Ответ GET /projects: папки архива + документы по проектам."""

    paths: list[str]
    projects: list[ProjectGroup]


class ArchiveScanSummary(BaseModel):
    """Итог POST /projects/scan."""

    found: int  # всего PDF в папках проектов (без дублей)
    new: int  # добавлено новых записей
    missing: int  # удалено: файлов больше нет на диске (индексы вычищены)
    duplicates: list[str]  # файлы-тёзки (slug занят) — не индексируются
    errors: list[str]  # файлы, не открывшиеся как PDF
    unavailable: list[str]  # недоступные папки (сетевой диск) — чистка пропущена
