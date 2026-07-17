"""Бизнес-логика модуля library.

Сканирует папку библиотеки и строит дерево, размечает PDF статусом
из БД (если уже индексированы). Открывает файл в системном просмотрщике
с проверкой, что путь находится внутри библиотеки.
"""

import json
import platform
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core import index_store, library_cache, progress
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
# Функция id документа по имени файла (для scoped-slug нужна метка папки).
SlugOf = Callable[[str], str]


def _folder_ids(paths: list[Path]) -> dict[Path, str | None]:
    """Метки всех папок, гарантированно уникальные между собой.

    Если папку скопировали вместе с `.search_index` (одинаковый folder_id),
    коллизию чиним: второй папке метка перевыдаётся (см.
    index_store.ensure_unique_folder_id). Персистим в meta.json, чтобы все
    читатели (дерево, resolve_folder, кеш) видели уже исправленные метки.
    """
    from indexing.embeddings_index import EMBEDDING_MODEL

    ids: dict[Path, str | None] = {}
    taken: set[str] = set()
    for lib in paths:
        fid = index_store.ensure_unique_folder_id(lib, taken, EMBEDDING_MODEL)
        ids[lib] = fid
        if fid:
            taken.add(fid)
    return ids


def _slug_fn(folder_id: str | None) -> SlugOf:
    """Строит функцию «имя файла → id документа» для конкретной папки."""

    def slug_of(name: str) -> str:
        base = make_document_id(name)
        return index_store.scoped_slug(folder_id, base) if folder_id else base

    return slug_of


def build_library_response(paths: list[Path], db: Session) -> LibraryResponse:
    """Дерево всех папок библиотеки + список висячих документов (файла нет).

    Одна папка → её дерево как есть. Несколько → общий синтетический корень
    «Knihovny» с папками внутри (фронтенд и фильтр «Kde hledat» рекурсивны,
    так что работают в обоих случаях без изменений).
    """
    docs_by_slug = {doc.slug: doc for doc in db.scalars(select(Document)).all()}

    def resolve(slug: str) -> tuple[str | None, bool, str | None, str | None]:
        doc = docs_by_slug.get(slug)
        if doc is None:
            return (None, False, None, None)
        return (doc.status, doc.pinned, doc.error_message, progress.get_progress(slug))

    folder_ids = _folder_ids(paths)
    subtrees = [_walk(lib, resolve, _slug_fn(folder_ids[lib])) for lib in paths]
    if len(subtrees) == 1:
        root = subtrees[0]
    else:
        root = LibraryFolder(name="Knihovny", path="", folders=subtrees, files=[])

    seen_slugs: set[str] = set()
    _collect_slugs(root, seen_slugs)
    orphans = [
        OrphanDocument(slug=doc.slug, title=doc.title, status=doc.status)
        for doc in docs_by_slug.values()
        if doc.slug not in seen_slugs
    ]
    return LibraryResponse(tree=root, orphans=orphans)


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

    tree = _walk(pdfs_root, resolve, make_document_id)
    # Корень _walk назвался бы «pdfs» (имя подпапки). Подменяем на имя бандла
    # (например «SharedLibrary») — так дерево читабельнее в UI.
    tree.name = pdfs_root.parent.name
    return LibraryResponse(tree=tree, orphans=[])


def _collect_slugs(folder: LibraryFolder, out: set[str]) -> None:
    for file in folder.files:
        out.add(file.slug)
    for sub in folder.folders:
        _collect_slugs(sub, out)


def _walk(folder: Path, resolve: StatusResolver, slug_of: SlugOf) -> LibraryFolder:
    folders: list[LibraryFolder] = []
    files: list[LibraryFile] = []
    for entry in sorted(folder.iterdir(), key=lambda p: p.name.lower()):
        # Скрытые файлы и системный мусор macOS — пропускаем.
        if entry.name.startswith("."):
            continue
        if entry.is_dir():
            folders.append(_walk(entry, resolve, slug_of))
        elif entry.suffix.lower() == ".pdf":
            slug = slug_of(entry.name)
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


def find_pdf_by_slug(paths: list[Path], slug: str) -> Path | None:
    """Ищет по папкам библиотеки PDF, чей id документа совпадает со slug.

    Метку папки из slug сводим к конкретной папке (index_store.resolve_folder),
    ищем только в ней — одноимённые файлы из других папок не спутаем. Если
    метки нет (легаси-slug), ищем во всех папках по имени файла.
    """
    folder = index_store.resolve_folder(paths, slug)
    if folder is not None:
        fid = index_store.folder_id_of(slug)
        for entry in folder.rglob("*.pdf"):
            if entry.name.startswith("."):
                continue
            if index_store.scoped_slug(fid, make_document_id(entry.name)) == slug:
                return entry
        return None
    # Легаси-slug без метки папки — ищем по имени файла во всех папках.
    for lib in paths:
        for entry in lib.rglob("*.pdf"):
            if entry.name.startswith("."):
                continue
            if make_document_id(entry.name) == slug:
                return entry
    return None


def scan_library(paths: list[Path], db: Session) -> ScanSummary:
    """Сканирует все папки библиотеки: НОВЫЕ PDF только регистрирует (pending).

    Скан бесплатный (обнаружение), индексация платная (vision LLM) — поэтому
    это два осознанных шага юзера: Skenovat → список «čeká» → Indexovat
    (start_indexing).

    Id документа = `{folder_id}__{файл}`, поэтому одноимённые файлы в РАЗНЫХ
    папках — разные документы. Коллизией остаётся только совпадение имён
    ВНУТРИ одной папки: такие файлы пропускаем и просим переименовать.

    Для каждого PDF:
      - если запись в БД есть (по slug) — дозаполняем relative_path при
        переезде;
      - если нет, но в `.search_index/{slug}` есть полный индекс на нашей
        модели — «усыновляем» (сразу ready, без трат);
      - иначе — Document(status='pending'), в пайплайн НЕ шлём.
    """
    from indexing.embeddings_index import EMBEDDING_MODEL

    docs_by_slug = {doc.slug: doc for doc in db.scalars(select(Document)).all()}
    summary = ScanSummary(created=0, already_indexed=0, adopted=0, duplicates=[])
    any_adopted = False
    folder_ids = _folder_ids(paths)

    for library_path in paths:
        folder_id = folder_ids[library_path]
        slug_of = _slug_fn(folder_id)
        # Усыновлять чужие индексы можно только на нашей модели эмбеддингов.
        meta = index_store.read_meta(library_path)
        can_adopt = meta is not None and meta.get("embedding_model") == EMBEDDING_MODEL

        pdf_paths = [
            p for p in sorted(library_path.rglob("*.pdf")) if not p.name.startswith(".")
        ]
        # Сколько файлов дают каждый slug ВНУТРИ этой папки. >1 — совпадение имён.
        slug_counts: dict[str, int] = {}
        for p in pdf_paths:
            slug_counts[slug_of(p.name)] = slug_counts.get(slug_of(p.name), 0) + 1

        for pdf_path in pdf_paths:
            slug = slug_of(pdf_path.name)
            relative_path = str(pdf_path.relative_to(library_path))

            if slug_counts[slug] > 1:
                summary.duplicates.append(relative_path)
                continue

            existing = docs_by_slug.get(slug)
            if existing is not None:
                if existing.relative_path != relative_path:
                    existing.relative_path = relative_path
                summary.already_indexed += 1
                continue

            if can_adopt and index_store.has_complete_index(library_path, slug):
                doc = Document(
                    slug=slug,
                    title=_adopted_title(library_path, slug) or pdf_path.stem,
                    status="ready",
                    relative_path=relative_path,
                )
                db.add(doc)
                db.commit()
                summary.adopted += 1
                any_adopted = True
                continue

            doc = Document(
                slug=slug,
                title=pdf_path.stem,  # реальный title подменит pipeline
                status="pending",
                relative_path=relative_path,
            )
            db.add(doc)
            db.commit()
            summary.created += 1

    db.commit()
    if any_adopted:
        # В пуле появились готовые документы без прогона пайплайна —
        # следующий вопрос должен их увидеть.
        library_cache.invalidate()
    return summary


def _adopted_title(library_path: Path, slug: str) -> str | None:
    """Название усыновляемого документа из descriptions.json, если оно там есть."""
    path = index_store.doc_dir(library_path, slug) / "descriptions.json"
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f).get("document_title") or None
    except (OSError, json.JSONDecodeError):
        return None


def start_indexing(
    paths: list[Path],
    db: Session,
    executor: ThreadPoolExecutor,
) -> int:
    """Отправляет все pending-документы в пайплайн, каждый — в свою папку.

    Статус сразу переводим в processing: повторный клик по «Indexovat» не
    отправит те же документы второй раз (двойная трата на vision), а после
    падения приложения их подхватит возобновление на старте. Артефакты
    пишутся в `<папка документа>/.search_index/{slug}` (папку определяем по
    метке в slug). Возвращает число отправленных.
    """
    pending = db.scalars(select(Document).where(Document.status == "pending")).all()
    submitted = 0
    for doc in pending:
        library_path = index_store.resolve_folder(paths, doc.slug)
        if library_path is None:
            continue  # папка документа отключена — пропускаем
        doc.status = "processing"
        db.commit()
        pdf_path = str(library_path / doc.relative_path) if doc.relative_path else None
        executor.submit(
            run_pipeline,
            doc.slug,
            pdf_path,
            index_store.doc_dir(library_path, doc.slug),
        )
        submitted += 1
    return submitted


def _is_within(target: Path, root: Path) -> bool:
    """target лежит внутри root (или совпадает с ним)?"""
    try:
        target.relative_to(root)
        return True
    except ValueError:
        return False


def open_file(paths: list[Path], file_path: str) -> None:
    """Открывает PDF в системном просмотрщике.

    Безопасность: файл должен находиться внутри одной из папок библиотеки,
    иначе через API можно открыть что угодно на диске.
    """
    target = Path(file_path).expanduser().resolve()
    if not any(_is_within(target, lib) for lib in paths):
        raise ValueError("Файл вне папок библиотеки")
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
