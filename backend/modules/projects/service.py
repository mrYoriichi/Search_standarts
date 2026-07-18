"""Сканирование папки архива проектов: обход, классификация PDF, slug'и.

Правило классификации (согласовано, см. PROJECT_STATE):
страница крупнее A3 → чертёжный лист ("sheet"), иначе текстовый
документ ("text") — TZ, статический расчёт, seznam příloh и т.п.
"""

import shutil
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

# Длинная сторона A3 = 420 мм ≈ 1191 pt. Берём с запасом на поля и кривой
# экспорт из CAD: всё, что длиннее ~1250 pt, — чертёжный формат (A2/A1/A0).
_SHEET_LONG_SIDE_PT = 1250


@dataclass
class FoundDocument:
    """PDF, найденный при сканировании архива (ещё не в БД)."""

    slug: str
    project: str
    relative_path: str
    doc_type: str  # "text" | "sheet"
    page_count: int


@dataclass
class ArchiveScanResult:
    """Итог обхода папки архива."""

    documents: list[FoundDocument]
    duplicates: list[str]  # relative_path файлов, чей slug уже занят (тёзки)
    skipped_root: list[str]  # PDF прямо в корне архива — вне проектов, не индексируем
    errors: list[str]  # файлы, которые не удалось открыть как PDF


def classify_pdf(pdf_path: Path) -> tuple[str, int]:
    """Определяет тип PDF по размеру первой страницы и считает страницы.

    Возвращает ("sheet" | "text", page_count). Кидает исключение,
    если файл не открывается как PDF, — обрабатывает вызывающий.
    """
    doc = pdfium.PdfDocument(pdf_path)
    try:
        page_count = len(doc)
        width, height = doc[0].get_size()
        long_side = max(width, height)
        doc_type = "sheet" if long_side > _SHEET_LONG_SIDE_PT else "text"
        return doc_type, page_count
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
    """Обходит папку архива и классифицирует все PDF.

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
            doc_type, page_count = classify_pdf(pdf_path)
        except Exception as error:
            errors.append(f"{relative}: {error}")
            continue

        seen_slugs.add(slug)
        documents.append(
            FoundDocument(
                slug=slug,
                project=project,
                relative_path=str(relative),
                doc_type=doc_type,
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
    Существующие — обновляем путь/тип/страницы (файл мог переехать).
    Пропавшие с диска — удаляем из БД вместе с индексами (наши артефакты
    в projects_data; файлы юзера не трогаем). Удалил проект из папки →
    «Skenovat» → проект ушёл и из поиска. Повторная обработка — заново
    за деньги, поэтому удаление папки = осознанное действие юзера.

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
    seen_slugs: set[str] = set()
    for root in roots:
        result = scan_archive(root, seen_slugs)
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
                    doc_type=found.doc_type,
                    page_count=found.page_count,
                    status="pending",
                )
            )
            new_count += 1
        else:
            doc.relative_path = found.relative_path
            doc.doc_type = found.doc_type
            doc.page_count = found.page_count

    removed = 0
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
    )


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
