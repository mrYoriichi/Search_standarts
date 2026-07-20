"""Бизнес-логика модуля library.

Сканирует папку библиотеки и строит дерево, размечает PDF статусом
из БД (если уже индексированы). Открывает файл в системном просмотрщике
с проверкой, что путь находится внутри библиотеки.
"""

import json
import os
import platform
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core import index_lock, index_store, library_cache, progress
from backend.modules.documents.models import Document
from backend.modules.documents.pipeline import run_pipeline_locked
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


def _unique_dirs(paths: list[Path]) -> list[Path]:
    """Убирает повторы одной и той же физической папки (симлинк/второй путь)."""
    result: list[Path] = []
    for p in paths:
        if any(index_store.same_dir(p, seen) for seen in result):
            continue
        result.append(p)
    return result


def _folder_ids(paths: list[Path]) -> dict[Path, str | None]:
    """Метки всех папок, гарантированно уникальные между собой.

    Если папку скопировали вместе с `.search_index` (одинаковый folder_id),
    коллизию чиним: второй папке метка перевыдаётся (см.
    index_store.ensure_unique_folder_id). Персистим в meta.json, чтобы все
    читатели (дерево, resolve_folder, кеш) видели уже исправленные метки.

    Одна и та же ФИЗИЧЕСКАЯ папка под двумя путями (симлинк, двойной маунт) —
    НЕ коллизия: обе записи получают общую метку, meta.json не трогаем. Иначе
    метка перевыдавалась бы «пинг-понгом» на каждый запрос, а документы
    становились бы сиротами.
    """
    from indexing.embeddings_index import EMBEDDING_MODEL

    ids: dict[Path, str | None] = {}
    taken: dict[str, Path] = {}
    for lib in paths:
        meta = index_store.read_meta(lib)
        existing = (meta or {}).get("folder_id")
        if (
            existing
            and existing in taken
            and index_store.same_dir(lib, taken[existing])
        ):
            ids[lib] = existing
            continue
        fid = index_store.ensure_unique_folder_id(lib, set(taken), EMBEDDING_MODEL)
        ids[lib] = fid
        if fid:
            taken[fid] = lib
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
    paths = _unique_dirs(paths)
    docs_by_slug = {doc.slug: doc for doc in db.scalars(select(Document)).all()}

    def resolve(slug: str) -> tuple[str | None, bool, str | None, str | None]:
        doc = docs_by_slug.get(slug)
        if doc is None:
            return (None, False, None, None)
        return (doc.status, doc.pinned, doc.error_message, progress.get_progress(slug))

    folder_ids = _folder_ids(paths)
    subtrees = []
    for lib in paths:
        try:
            subtrees.append(_walk(lib, resolve, _slug_fn(folder_ids[lib])))
        except OSError:
            # Папка недоступна (отвалился сетевой диск) — показываем пустой
            # узел с пометкой; остальные папки и вся страница живут дальше.
            subtrees.append(
                LibraryFolder(
                    name=f"{lib.name} (nedostupná)",
                    path=str(lib),
                    folders=[],
                    files=[],
                )
            )
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


def resolve_pdf_by_slug(db: Session, slug: str) -> Path | None:
    """Путь к PDF документа по slug — по ВСЕМ пулам (библиотека + архив).

    Единственное место, знающее оба пула: им пользуются раздача PDF
    (`GET /library/pdf/{slug}`) и сильный поиск (рендер страниц источников).
    """
    from backend.modules.projects import service as projects_service
    from backend.modules.projects.models import ProjectDocument
    from backend.modules.settings import service as settings_service

    library_paths = settings_service.get_library_paths(db)
    if library_paths:
        pdf_path = find_pdf_by_slug([Path(p) for p in library_paths], slug)
        if pdf_path is not None:
            return pdf_path

    # Архив проектов: relative_path знает БД, папку — по наличию файла.
    projects_paths = [Path(p) for p in settings_service.get_projects_paths(db)]
    pdoc = db.scalar(select(ProjectDocument).where(ProjectDocument.slug == slug))
    if projects_paths and pdoc is not None:
        root = projects_service.resolve_project_root(projects_paths, pdoc.relative_path)
        if root is not None:
            return root / pdoc.relative_path
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

    paths = _unique_dirs(paths)
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

        try:
            pdf_paths = [
                p
                for p in sorted(library_path.rglob("*.pdf"))
                if not p.name.startswith(".")
            ]
        except OSError:
            continue  # папка недоступна (сетевой диск) — скан остальных живёт
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


# Сериализует одновременные POST /library/index (даблклик): без этого оба
# запроса успевали прочитать одни и те же pending до чужого commit —
# документ уходил в пайплайн дважды (двойная оплата vision).
_start_indexing_lock = threading.Lock()


def start_indexing(
    paths: list[Path],
    db: Session,
    executor: ThreadPoolExecutor,
) -> tuple[int, list[str]]:
    """Отправляет pending-документы в пайплайн, каждый — в свою папку.

    Статус сразу переводим в processing: повторный клик по «Indexovat» не
    отправит те же документы второй раз (двойная трата на vision), а после
    падения приложения их подхватит возобновление на старте. Артефакты
    пишутся в `<папка документа>/.search_index/{slug}`.

    Папку перед индексацией запираем лок-файлом: если её уже индексирует
    другая машина (общая сетевая папка) — документы этой папки НЕ трогаем,
    оставляем pending и сообщаем, кто занят. Возвращает (сколько отправлено,
    список «папка: кто индексирует»).
    """
    with _start_indexing_lock:
        pending = db.scalars(select(Document).where(Document.status == "pending")).all()

        # Группируем pending по папкам — лок берём один на папку.
        by_folder: dict[Path, list[Document]] = {}
        for doc in pending:
            library_path = index_store.resolve_folder(paths, doc.slug)
            if library_path is None:
                continue  # папка документа отключена — пропускаем
            by_folder.setdefault(library_path, []).append(doc)

        submitted = 0
        locked: list[str] = []
        for library_path, docs in by_folder.items():
            busy_owner = index_lock.acquire(library_path)
            if busy_owner is not None:
                locked.append(f"{library_path.name}: {busy_owner}")
                continue  # держит другая машина — оставляем документы pending
            index_lock.register(library_path, len(docs))
            for doc in docs:
                doc.status = "processing"
            db.commit()
            for doc in docs:
                pdf_path = (
                    str(library_path / doc.relative_path) if doc.relative_path else None
                )
                executor.submit(
                    run_pipeline_locked,
                    library_path,
                    doc.slug,
                    pdf_path,
                    index_store.doc_dir(library_path, doc.slug),
                )
                submitted += 1
        return submitted, locked


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
        # startfile = ShellExecute, открывает файл ассоциированной программой.
        # НЕ shell-команда `start`: через неё имя файла вида `a&calc.pdf`
        # из общей папки исполнило бы команду.
        os.startfile(str(target))  # существует только на Windows
    else:
        subprocess.run(["xdg-open", str(target)], check=False)
