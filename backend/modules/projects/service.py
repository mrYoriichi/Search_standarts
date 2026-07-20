"""Сканирование папки архива проектов: обход PDF, slug'и.

Классификации sheet/text больше нет (шаг 3 универсального пайплайна):
все документы идут через общий по-страничный роутер, при скане только
считаем страницы и отсеиваем битые PDF.
"""

import shutil
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import pypdfium2 as pdfium
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core import progress
from backend.modules.projects.models import ProjectDocument
from backend.modules.projects.schemas import (
    ArchiveResponse,
    ArchiveScanSummary,
    ProjectDocumentOut,
    ProjectGroup,
)
from pdf_processing.parser import make_document_id
from pdf_processing.pdfium_lock import PDFIUM_LOCK


@dataclass
class FoundDocument:
    """PDF, найденный при сканировании архива (ещё не в БД)."""

    slug: str
    project: str
    relative_path: str
    page_count: int


@dataclass
class ArchiveScanResult:
    """Итог обхода папки архива."""

    documents: list[FoundDocument]
    duplicates: list[str]  # relative_path файлов, чей slug уже занят (тёзки)
    skipped_root: list[str]  # PDF прямо в корне архива — вне проектов, не индексируем
    errors: list[str]  # файлы, которые не удалось открыть как PDF


def count_pages(pdf_path: Path) -> int:
    """Число страниц PDF (для UI) + бесплатный отсев битых файлов.

    Кидает исключение, если файл не открывается как PDF, —
    обрабатывает вызывающий (уходит в errors скана).
    """
    with PDFIUM_LOCK:
        doc = pdfium.PdfDocument(pdf_path)
        try:
            return len(doc)
        finally:
            doc.close()


def make_project_slug(project: str, filename: str) -> str:
    """Slug документа архива: {проект}__{имя файла}.

    Двойное подчёркивание — разделитель, чтобы обе части читались.
    Имена файлов повторяются между проектами (TZ.pdf есть везде),
    поэтому проект — обязательная часть идентичности (решение — вариант А).
    """
    return f"{make_document_id(project)}__{make_document_id(filename)}"


def resolve_project_root(paths: list[Path], relative_path: str) -> Path | None:
    """Папка архива, в которой реально лежит файл по relative_path.

    Архивы не хранят метку папки (slug = `{проект}__{файл}` и так не зависит
    от пути), поэтому папку документа определяем по наличию файла на диске.
    Первая совпавшая — как и порядок дедупа при скане. None — файла нет нигде.
    """
    for root in paths:
        if (root / relative_path).exists():
            return root
    return None


def scan_archive(root: Path, seen_slugs: set[str] | None = None) -> ArchiveScanResult:
    """Обходит папку архива и собирает все PDF.

    Проект = папка первого уровня. PDF прямо в корне архива не индексируем
    (не к чему привязать), но сообщаем о них в skipped_root.
    Файловую систему только читаем (принцип #16). seen_slugs — общий набор
    занятых slug'ов (при обходе нескольких папок архива): тёзки между папками
    тоже коллизия (один и тот же проект+файл), уходят в duplicates.
    """
    documents: list[FoundDocument] = []
    duplicates: list[str] = []
    skipped_root: list[str] = []
    errors: list[str] = []
    if seen_slugs is None:
        seen_slugs = set()

    for pdf_path in sorted(root.rglob("*.pdf")):
        relative = pdf_path.relative_to(root)
        if len(relative.parts) == 1:
            skipped_root.append(str(relative))
            continue

        project = relative.parts[0]
        slug = make_project_slug(project, pdf_path.name)
        if slug in seen_slugs:
            duplicates.append(str(relative))
            continue

        try:
            page_count = count_pages(pdf_path)
        except Exception as error:
            errors.append(f"{relative}: {error}")
            continue

        seen_slugs.add(slug)
        documents.append(
            FoundDocument(
                slug=slug,
                project=project,
                # as_posix: на Windows str() дал бы `\` — фронт делит путь
                # по `/`, а склейка root / path понимает `/` на всех ОС.
                relative_path=relative.as_posix(),
                page_count=page_count,
            )
        )

    return ArchiveScanResult(
        documents=documents,
        duplicates=duplicates,
        skipped_root=skipped_root,
        errors=errors,
    )


def sync_archive(db: Session, roots: list[Path]) -> ArchiveScanSummary:
    """Сканирует все папки архива и синхронизирует таблицу project_documents.

    Новые файлы — вставляем со статусом "pending".
    Существующие — обновляем путь/страницы (файл мог переехать).
    Пропавшие с диска — удаляем из БД вместе с индексами (наши артефакты
    в projects_data; файлы юзера не трогаем). Удалил проект из папки →
    «Skenovat» → проект ушёл и из поиска. Повторная обработка — заново
    за деньги, поэтому удаление папки = осознанное действие юзера.
    Недоступная папка (сетевой диск отвалился) — НЕ «пропавшие»: она уходит
    в unavailable, и чистка в этот скан пропускается целиком.

    slug (`{проект}__{файл}`) уникален по ВСЕМ папкам архива: тёзки между
    папками — коллизия, уходят в duplicates.
    """
    from backend.core import library_cache
    from backend.core.paths import PROJECTS_DATA_DIR

    # Общий обход всех папок с единым набором занятых slug'ов.
    documents: list[FoundDocument] = []
    duplicates: list[str] = []
    skipped_root: list[str] = []
    errors: list[str] = []
    unavailable: list[str] = []
    seen_slugs: set[str] = set()
    for root in roots:
        # Недоступная папка (отвалился сетевой диск) неотличима от пустой:
        # rglob по несуществующему пути молча даёт пустой список — и чистка
        # ниже снесла бы записи и индексы живых документов.
        if not root.is_dir():
            unavailable.append(str(root))
            continue
        try:
            result = scan_archive(root, seen_slugs)
        except OSError:
            unavailable.append(str(root))
            continue
        documents.extend(result.documents)
        duplicates.extend(result.duplicates)
        skipped_root.extend(result.skipped_root)
        errors.extend(result.errors)

    existing = {doc.slug: doc for doc in db.scalars(select(ProjectDocument)).all()}
    found_slugs: set[str] = set()
    new_count = 0

    for found in documents:
        found_slugs.add(found.slug)
        doc = existing.get(found.slug)
        if doc is None:
            db.add(
                ProjectDocument(
                    slug=found.slug,
                    project=found.project,
                    relative_path=found.relative_path,
                    # Колонка NOT NULL без default в живых БД (SQLite не умеет
                    # снять NOT NULL) — пишем константу, развилки больше нет.
                    doc_type="text",
                    page_count=found.page_count,
                    status="pending",
                )
            )
            new_count += 1
        else:
            doc.relative_path = found.relative_path
            doc.page_count = found.page_count

    removed = 0
    # Документы архива не несут метку папки (slug = {проект}__{файл}),
    # поэтому при ЛЮБОЙ недоступной папке чистку пропускаем целиком — не
    # понять, чьи «пропавшие». Вернётся диск — следующий скан дочистит.
    if not unavailable:
        for slug, doc in existing.items():
            if slug in found_slugs:
                continue
            if doc.status == "processing":
                continue  # обрабатывается прямо сейчас — не выдёргиваем из-под ног
            shutil.rmtree(PROJECTS_DATA_DIR / slug, ignore_errors=True)
            db.delete(doc)
            removed += 1

    db.commit()
    if removed:
        library_cache.invalidate()

    return ArchiveScanSummary(
        found=len(documents),
        new=new_count,
        missing=removed,
        duplicates=duplicates,
        skipped_root=skipped_root,
        errors=errors,
        unavailable=unavailable,
    )


class DocumentBusyError(Exception):
    """Операция отклонена: документ архива сейчас обрабатывается пайплайном.

    Переиндексация во время работы фонового pipeline даёт гонку: пайплайн
    дописал бы артефакты уже ПОСЛЕ rmtree — файлы и статус разъехались бы.
    """


def reindex_document(
    db: Session,
    slug: str,
    paths: list[Path],
    executor: ThreadPoolExecutor,
) -> ProjectDocument:
    """Полностью переобрабатывает документ архива: старые артефакты удаляются.

    Нужно после смены пайплайна (шаг 3: бывшие sheet-документы) или когда
    юзер заменил содержимое PDF. Сам PDF в папке архива НЕ трогаем.
    Межмашинный лок не нужен: артефакты архива лежат в локальной
    PROJECTS_DATA_DIR, а не в общей сетевой папке.
    """
    from backend.core import library_cache
    from backend.core.paths import PROJECTS_DATA_DIR
    from backend.modules.projects.pipeline import run_project_pipeline

    doc = db.scalar(select(ProjectDocument).where(ProjectDocument.slug == slug))
    if doc is None:
        raise ValueError(f"Документ архива {slug} не найден")
    if doc.status == "processing":
        raise DocumentBusyError(
            f"Документ {slug} сейчас индексируется — дождись конца обработки"
        )

    root = resolve_project_root(paths, doc.relative_path)
    if root is None:
        raise ValueError(f"PDF не найден ни в одной папке архива: {doc.relative_path}")

    shutil.rmtree(PROJECTS_DATA_DIR / slug, ignore_errors=True)

    doc.status = "processing"
    doc.error = None
    db.commit()

    # Старые чанки уже удалены с диска — убираем их из кеша сразу, не дожидаясь
    # конца переобработки (pipeline сбросит кеш ещё раз, когда документ готов).
    library_cache.invalidate()

    executor.submit(run_project_pipeline, slug, str(root / doc.relative_path))
    return doc


def toggle_pin(db: Session, slug: str) -> ProjectDocument:
    """Переключает закреплённость документа архива. ValueError, если не найден."""
    doc = db.scalar(select(ProjectDocument).where(ProjectDocument.slug == slug))
    if doc is None:
        raise ValueError(f"Документ архива {slug} не найден")
    doc.pinned = not doc.pinned
    db.commit()
    return doc


def build_archive_response(db: Session, paths: list[str]) -> ArchiveResponse:
    """Документы архива из БД, сгруппированные по проектам (для UI)."""
    docs = db.scalars(
        select(ProjectDocument).order_by(
            ProjectDocument.project, ProjectDocument.relative_path
        )
    ).all()

    groups: dict[str, list[ProjectDocumentOut]] = {}
    for doc in docs:
        out = ProjectDocumentOut.model_validate(doc)
        out.progress = progress.get_progress(doc.slug)
        groups.setdefault(doc.project, []).append(out)

    return ArchiveResponse(
        paths=paths,
        projects=[
            ProjectGroup(name=name, documents=items) for name, items in groups.items()
        ],
    )
