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
    pinned: bool


class LibraryFolder(BaseModel):
    """Папка в дереве библиотеки. Может содержать подпапки и PDF."""

    name: str
    path: str  # абсолютный путь к папке
    folders: list["LibraryFolder"]
    files: list[LibraryFile]


class OrphanDocument(BaseModel):
    """Документ в БД, чей PDF исчез из папки библиотеки.

    Юзер мог удалить файл или переименовать. UI показывает их в отдельной
    секции «Висячие» с кнопками «Это переименование» и (в будущем) «Убрать».
    """

    slug: str
    title: str
    status: str


class LibraryResponse(BaseModel):
    """Полный ответ GET /api/library: дерево + висячие документы."""

    tree: LibraryFolder
    orphans: list[OrphanDocument]


class ScanSummary(BaseModel):
    """Ответ POST /api/library/scan: сколько PDF было найдено и что с ними сделали."""

    created: int  # новые документы, отправленные в pipeline
    already_indexed: int  # PDF, для которых запись в БД уже есть
