"""Бизнес-логика модуля library.

Сканирует папку библиотеки и строит дерево, размечает PDF статусом
из БД (если уже индексированы). Открывает файл в системном просмотрщике
с проверкой, что путь находится внутри библиотеки.
"""

import platform
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core import progress
from backend.modules.documents.models import Document
from backend.modules.documents.pipeline import run_pipeline
from backend.modules.library.schemas import (
    LibraryFile,
    LibraryFolder,
    LibraryResponse,
    OrphanDocument,
    ScanSummary,
)
from pdf_processing.parser import make_document_id


# Резолвер статуса PDF по slug: (status, pinned, error, progress). Различает пул
# юзера (статус из БД) и общую базу (статус по наличию индексов). Так дерево
# строится одним _walk. error — причина падения, progress — текущая стадия
# обработки (оба только у пула юзера, иначе None).
StatusResolver = Callable[[str], tuple[str | None, bool, str | None, str | None]]


def build_library_response(library_path: Path, db: Session) -> LibraryResponse:
    """Возвращает дерево папки юзера + список висячих документов (нет файла в папке)."""
    docs_by_slug = {doc.slug: doc for doc in db.scalars(select(Document)).all()}

    def resolve(slug: str) -> tuple[str | None, bool, str | None, str | None]:
        doc = docs_by_slug.get(slug)
        if doc is None:
            return (None, False, None, None)
        return (doc.status, doc.pinned, doc.error_message, progress.get_progress(slug))

    tree = _walk(library_path, resolve)
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


def build_shared_library_response(
    pdfs_root: Path, data_root: Path, pinned_slugs: set[str] | None = None
) -> LibraryResponse:
    """Дерево общей базы из её папки с PDF (`<shared>/pdfs`).

    Статус «ready» — если для slug есть индексы в `<shared>/raw_data/{slug}`.
    Общая база read-only, в БД её нет, поэтому статус берём с диска, а пины —
    из переданного множества (хранится в настройках). Висячих нет."""
    pinned = pinned_slugs or set()

    def resolve(slug: str) -> tuple[str | None, bool, str | None, str | None]:
        doc_dir = data_root / slug
        ready = (doc_dir / "chunks.json").exists() and (
            doc_dir / "embeddings.json"
        ).exists()
        return ("ready" if ready else None, slug in pinned, None, None)

    tree = _walk(pdfs_root, resolve)
    # Корень _walk назвался бы «pdfs» (имя подпапки). Подменяем на имя бандла
    # (например «SharedLibrary») — так дерево читабельнее в UI.
    tree.name = pdfs_root.parent.name
    return LibraryResponse(tree=tree, orphans=[])


def _collect_slugs(folder: LibraryFolder, out: set[str]) -> None:
    for file in folder.files:
        out.add(file.slug)
    for sub in folder.folders:
        _collect_slugs(sub, out)


def _walk(folder: Path, resolve: StatusResolver) -> LibraryFolder:
    folders: list[LibraryFolder] = []
    files: list[LibraryFile] = []
    for entry in sorted(folder.iterdir(), key=lambda p: p.name.lower()):
        # Скрытые файлы и системный мусор macOS — пропускаем.
        if entry.name.startswith("."):
            continue
        if entry.is_dir():
            folders.append(_walk(entry, resolve))
        elif entry.suffix.lower() == ".pdf":
            slug = make_document_id(entry.name)
            status, pinned, error, doc_progress = resolve(slug)
            files.append(
                LibraryFile(
                    name=entry.name,
                    path=str(entry),
                    slug=slug,
                    status=status,
                    pinned=pinned,
                    error=error,
                    progress=doc_progress,
                )
            )
    return LibraryFolder(
        name=folder.name, path=str(folder), folders=folders, files=files
    )


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


def scan_library(
    library_path: Path,
    db: Session,
) -> ScanSummary:
    """Сканирует папку библиотеки: НОВЫЕ PDF только регистрирует (pending).

    Скан бесплатный (обнаружение), индексация платная (vision LLM) — поэтому
    это два осознанных шага юзера: Skenovat → список «čeká» → Indexovat
    (start_indexing).

    Для каждого PDF:
      - если запись в БД есть (по slug) — пропускаем, но дозаполняем
        relative_path, если он был пустой (миграция старых записей);
      - если нет — создаём Document(status='pending'), в пайплайн НЕ шлём.

    Сам файл юзера НЕ копируем — pipeline прочитает PDF прямо из библиотеки.

    Если два разных файла дают одно имя (id) — это коллизия: мы не можем их
    различить. Такие файлы НЕ трогаем и возвращаем в duplicates, чтобы юзер
    переименовал. Иначе один молча перезатёр бы индекс другого.
    """
    docs_by_slug = {doc.slug: doc for doc in db.scalars(select(Document)).all()}

    # Все PDF библиотеки (без скрытых файлов).
    pdf_paths = [
        p for p in sorted(library_path.rglob("*.pdf")) if not p.name.startswith(".")
    ]

    # Первый проход: сколько файлов дают каждый slug. >1 — совпадение имён.
    slug_counts: dict[str, int] = {}
    for p in pdf_paths:
        slug = make_document_id(p.name)
        slug_counts[slug] = slug_counts.get(slug, 0) + 1

    created = 0
    already_indexed = 0
    duplicates: list[str] = []

    for pdf_path in pdf_paths:
        slug = make_document_id(pdf_path.name)
        relative_path = str(pdf_path.relative_to(library_path))

        # Совпадение имён — пропускаем все такие файлы и сообщаем юзеру.
        if slug_counts[slug] > 1:
            duplicates.append(relative_path)
            continue

        existing = docs_by_slug.get(slug)
        if existing is not None:
            # Дозаполняем путь у старых записей (был None) И обновляем, если файл
            # переехал в другую папку — иначе «Переиндексировать» искал бы PDF
            # по старому пути и падал бы с «PDF не найден».
            if existing.relative_path != relative_path:
                existing.relative_path = relative_path
            already_indexed += 1
            continue

        title = pdf_path.stem  # имя без расширения; реальный title подменит pipeline
        doc = Document(
            slug=slug,
            title=title,
            status="pending",
            relative_path=relative_path,
        )
        db.add(doc)
        db.commit()
        created += 1

    db.commit()
    return ScanSummary(
        created=created, already_indexed=already_indexed, duplicates=duplicates
    )


def start_indexing(
    library_path: Path,
    db: Session,
    executor: ThreadPoolExecutor,
) -> int:
    """Отправляет все pending-документы библиотеки в пайплайн.

    Статус сразу переводим в processing: повторный клик по «Indexovat» не
    отправит те же документы второй раз (двойная трата на vision), а после
    падения приложения их подхватит возобновление на старте.
    Возвращает число отправленных.
    """
    pending = db.scalars(select(Document).where(Document.status == "pending")).all()
    for doc in pending:
        doc.status = "processing"
    db.commit()
    for doc in pending:
        pdf_path = str(library_path / doc.relative_path) if doc.relative_path else None
        executor.submit(run_pipeline, doc.slug, pdf_path)
    return len(pending)


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
