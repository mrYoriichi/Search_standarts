"""Pydantic-схемы для эндпоинтов модуля library.

Возвращаем папку библиотеки в виде дерева: каждая папка содержит
вложенные папки и PDF-файлы. У PDF — статус обработки (если есть запись
в БД), иначе None («не индексирован»).
"""

from pydantic import BaseModel


class LibraryFile(BaseModel):
    """PDF-файл в папке библиотеки."""

    name: str
    path: str  # абсолютный путь к файлу на диске
    slug: str  # id, который получился бы при индексации (для матчинга с Document)
    # status — None, если документ ещё не в БД (не индексирован).
    # Иначе processing/ready/failed.
    status: str | None


class LibraryFolder(BaseModel):
    """Папка в дереве библиотеки. Может содержать подпапки и PDF."""

    name: str
    path: str  # абсолютный путь к папке
    folders: list["LibraryFolder"]
    files: list[LibraryFile]
