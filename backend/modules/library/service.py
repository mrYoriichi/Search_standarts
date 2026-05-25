"""Бизнес-логика модуля library.

Сканирует папку библиотеки и строит дерево, размечает PDF статусом
из БД (если уже индексированы). Открывает файл в системном просмотрщике
с проверкой, что путь находится внутри библиотеки.
"""

import platform
import subprocess
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.modules.documents.models import Document
from backend.modules.library.schemas import (
    LibraryFile,
    LibraryFolder,
    LibraryResponse,
    OrphanDocument,
)
from pdf_processing.parser import make_document_id


def build_library_response(library_path: Path, db: Session) -> LibraryResponse:
    """Возвращает дерево папки + список висячих документов (нет файла в папке)."""
    docs_by_slug = {doc.slug: doc for doc in db.scalars(select(Document)).all()}
    tree = _walk(library_path, docs_by_slug)
    # Собираем slug'и всех PDF, реально лежащих в папке (включая подпапки).
    seen_slugs: set[str] = set()
    _collect_slugs(tree, seen_slugs)
    # Висячие = всё, что есть в БД, но не нашлось в папке.
    orphans = [
        OrphanDocument(slug=doc.slug, title=doc.title, status=doc.status)
        for doc in docs_by_slug.values()
        if doc.slug not in seen_slugs
    ]
    return LibraryResponse(tree=tree, orphans=orphans)


def _collect_slugs(folder: LibraryFolder, out: set[str]) -> None:
    for file in folder.files:
        out.add(file.slug)
    for sub in folder.folders:
        _collect_slugs(sub, out)


def _walk(folder: Path, docs_by_slug: dict[str, Document]) -> LibraryFolder:
    folders: list[LibraryFolder] = []
    files: list[LibraryFile] = []
    for entry in sorted(folder.iterdir(), key=lambda p: p.name.lower()):
        # Скрытые файлы и системный мусор macOS — пропускаем.
        if entry.name.startswith("."):
            continue
        if entry.is_dir():
            folders.append(_walk(entry, docs_by_slug))
        elif entry.suffix.lower() == ".pdf":
            slug = make_document_id(entry.name)
            doc = docs_by_slug.get(slug)
            files.append(
                LibraryFile(
                    name=entry.name,
                    path=str(entry),
                    slug=slug,
                    status=doc.status if doc else None,
                    pinned=doc.pinned if doc else False,
                )
            )
    return LibraryFolder(name=folder.name, path=str(folder), folders=folders, files=files)


def find_pdf_by_slug(library_path: Path, slug: str) -> Path | None:
    """Ищет в папке библиотеки (рекурсивно) PDF, у которого slug совпадает.

    Slug строится из имени файла (make_document_id), так что один проход —
    O(N) от количества PDF. Для библиотеки в ~200 файлов — миллисекунды.
    """
    for entry in library_path.rglob("*.pdf"):
        if entry.name.startswith("."):
            continue
        if make_document_id(entry.name) == slug:
            return entry
    return None


def open_file(library_path: Path, file_path: str) -> None:
    """Открывает PDF в системном просмотрщике.

    Безопасность: файл должен находиться внутри library_path,
    иначе через API можно открыть что угодно на диске.
    """
    target = Path(file_path).expanduser().resolve()
    try:
        target.relative_to(library_path)
    except ValueError as exc:
        raise ValueError("Файл вне папки библиотеки") from exc
    if not target.is_file():
        raise ValueError(f"Файл не найден: {target}")

    system = platform.system()
    if system == "Darwin":
        subprocess.run(["open", str(target)], check=False)
    elif system == "Windows":
        # На Windows `start` — это shell-команда, не отдельный exe.
        subprocess.run(["start", "", str(target)], shell=True, check=False)
    else:
        subprocess.run(["xdg-open", str(target)], check=False)
