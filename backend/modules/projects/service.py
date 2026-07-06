"""Сканирование папки архива проектов: обход, классификация PDF, slug'и.

Правило классификации (согласовано, см. PROJECT_STATE):
страница крупнее A3 → чертёжный лист ("sheet"), иначе текстовый
документ ("text") — TZ, статический расчёт, seznam příloh и т.п.
"""

from dataclasses import dataclass
from pathlib import Path

import pypdfium2 as pdfium
from sqlalchemy import select
from sqlalchemy.orm import Session

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


def scan_archive(root: Path) -> ArchiveScanResult:
    """Обходит папку архива и классифицирует все PDF.

    Проект = папка первого уровня. PDF прямо в корне архива не индексируем
    (не к чему привязать), но сообщаем о них в skipped_root.
    Файловую систему только читаем (принцип #16).
    """
    documents: list[FoundDocument] = []
    duplicates: list[str] = []
    skipped_root: list[str] = []
    errors: list[str] = []
    seen_slugs: set[str] = set()

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


def sync_archive(db: Session, root: Path) -> ArchiveScanSummary:
    """Сканирует папку архива и синхронизирует таблицу project_documents.

    Новые файлы — вставляем со статусом "pending" (индексация — этап 2).
    Существующие — обновляем путь/тип/страницы (файл мог переехать).
    Пропавшие с диска — только считаем, из БД не удаляем (решает юзер).
    """
    result = scan_archive(root)

    existing = {
        doc.slug: doc for doc in db.scalars(select(ProjectDocument)).all()
    }
    found_slugs: set[str] = set()
    new_count = 0

    for found in result.documents:
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

    missing = len([slug for slug in existing if slug not in found_slugs])
    db.commit()

    return ArchiveScanSummary(
        found=len(result.documents),
        new=new_count,
        missing=missing,
        duplicates=result.duplicates,
        skipped_root=result.skipped_root,
        errors=result.errors,
    )


def build_archive_response(db: Session, path: str | None) -> ArchiveResponse:
    """Документы архива из БД, сгруппированные по проектам (для UI)."""
    docs = db.scalars(
        select(ProjectDocument).order_by(
            ProjectDocument.project, ProjectDocument.relative_path
        )
    ).all()

    groups: dict[str, list[ProjectDocumentOut]] = {}
    for doc in docs:
        groups.setdefault(doc.project, []).append(
            ProjectDocumentOut.model_validate(doc)
        )

    return ArchiveResponse(
        path=path,
        projects=[
            ProjectGroup(name=name, documents=items)
            for name, items in groups.items()
        ],
    )
