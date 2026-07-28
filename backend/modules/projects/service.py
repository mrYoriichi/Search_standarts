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
    file_size: int
    file_mtime: float


@dataclass
class ArchiveScanResult:
    """Итог обхода папки проекта."""

    documents: list[FoundDocument]
    duplicates: list[str]  # relative_path файлов, чей slug уже занят (тёзки)
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


def make_project_slug(project: str, relative_path: str) -> str:
    """Slug документа архива: {проект}__{путь внутри проекта}.

    Проект — имя подключённой папки. Путь, а не только имя файла, — потому что
    одноимённые PDF лежат в разных подпапках проекта (TZ/, výkresy/).
    Слэши превращаем в пробелы: make_document_id сведёт их к `_`.
    """
    return f"{make_document_id(project)}__{make_document_id(relative_path.replace('/', ' '))}"


def resolve_project_root(
    paths: list[Path], project: str, relative_path: str
) -> Path | None:
    """Папка проекта, в которой реально лежит файл по relative_path.

    Сверяем и имя папки (= имя проекта), и наличие файла: relative_path
    вида `TZ/tz.pdf` может существовать сразу в нескольких проектах, и без
    проверки имени pipeline обработал бы чужой файл. None — не нашли.
    """
    for root in paths:
        if root.name == project and (root / relative_path).exists():
            return root
    return None


def scan_archive(root: Path, seen_slugs: set[str] | None = None) -> ArchiveScanResult:
    """Обходит папку проекта и собирает все PDF.

    Подключённая папка целиком = один проект с именем этой папки; PDF берём
    с любой глубины, включая корень. Файловую систему только читаем
    (принцип #16). seen_slugs — общий набор занятых slug'ов (при обходе
    нескольких папок): тёзки между папками-проектами с одинаковым именем —
    коллизия, уходят в duplicates.
    """
    documents: list[FoundDocument] = []
    duplicates: list[str] = []
    errors: list[str] = []
    if seen_slugs is None:
        seen_slugs = set()

    project = root.name
    for pdf_path in sorted(root.rglob("*.pdf")):
        relative = pdf_path.relative_to(root)
        slug = make_project_slug(project, relative.as_posix())
        if slug in seen_slugs:
            duplicates.append(str(relative))
            continue

        try:
            page_count = count_pages(pdf_path)
            stat = pdf_path.stat()
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
                file_size=stat.st_size,
                file_mtime=stat.st_mtime,
            )
        )

    return ArchiveScanResult(
        documents=documents,
        duplicates=duplicates,
        errors=errors,
    )


def sync_archive(db: Session, roots: list[Path]) -> ArchiveScanSummary:
    """Сканирует все папки проектов и синхронизирует таблицу project_documents.

    Новые файлы — вставляем со статусом "pending".
    Существующие — обновляем путь/страницы (файл мог переехать).
    Пропавшие с диска — удаляем из БД вместе с индексами (наши артефакты
    в projects_data; файлы юзера не трогаем). Удалил проект из папки →
    «Skenovat» → проект ушёл и из поиска. Повторная обработка — заново
    за деньги, поэтому удаление папки = осознанное действие юзера.
    Недоступная папка (сетевой диск отвалился) — НЕ «пропавшие»: она уходит
    в unavailable, и чистка в этот скан пропускается целиком.

    slug (`{проект}__{путь}`) уникален по ВСЕМ папкам: тёзки между
    папками-проектами с одинаковым именем — коллизия, уходят в duplicates.
    """
    from backend.core import library_cache
    from backend.core.paths import PROJECTS_DATA_DIR

    # Общий обход всех папок с единым набором занятых slug'ов.
    documents: list[FoundDocument] = []
    duplicates: list[str] = []
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
        errors.extend(result.errors)

    existing = {doc.slug: doc for doc in db.scalars(select(ProjectDocument)).all()}
    found_slugs: set[str] = set()
    new_count = 0
    changed = 0

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
                    file_size=found.file_size,
                    file_mtime=found.file_mtime,
                )
            )
            new_count += 1
        elif doc.status == "processing":
            # Обрабатывается прямо сейчас — путь/страницы обновим, stat НЕ
            # трогаем: замену файла под пайплайном поймает следующий скан.
            doc.relative_path = found.relative_path
            doc.page_count = found.page_count
        elif doc.file_size is None:
            # Строка со старой версии (stat-колонок не было): дозаполняем БЕЗ
            # сброса — иначе первый скан после обновления снёс бы весь архив
            # в pending, а это повторная оплата vision.
            doc.relative_path = found.relative_path
            doc.page_count = found.page_count
            doc.file_size = found.file_size
            doc.file_mtime = found.file_mtime
        elif (doc.file_size, doc.file_mtime) != (found.file_size, found.file_mtime):
            # Файл заменили (тот же путь, новое содержимое): старые чанки
            # устарели — вычищаем и возвращаем в pending. Индексация — платная,
            # поэтому НЕ автозапуск: юзер нажмёт «Indexovat».
            shutil.rmtree(PROJECTS_DATA_DIR / found.slug, ignore_errors=True)
            doc.relative_path = found.relative_path
            doc.page_count = found.page_count
            doc.status = "pending"
            doc.error = None
            doc.file_size = found.file_size
            doc.file_mtime = found.file_mtime
            changed += 1
        else:
            doc.relative_path = found.relative_path
            doc.page_count = found.page_count

    removed = 0
    # Документы архива не несут метку папки (slug = {проект}__{путь}),
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
    if removed or changed:
        # С диска пропали чанки (удалённые или заменённые документы) —
        # кеш поиска не должен их отдавать.
        library_cache.invalidate()

    return ArchiveScanSummary(
        found=len(documents),
        new=new_count,
        missing=removed,
        changed=changed,
        duplicates=duplicates,
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

    root = resolve_project_root(paths, doc.project, doc.relative_path)
    if root is None:
        raise ValueError(f"PDF не найден ни в одной папке архива: {doc.relative_path}")

    shutil.rmtree(PROJECTS_DATA_DIR / slug, ignore_errors=True)

    doc.status = "processing"
    doc.error = None
    # Свежий stat: иначе следующий скан сверил бы старые значения и зря
    # сбросил бы только что переиндексированный документ в pending.
    stat = (root / doc.relative_path).stat()
    doc.file_size = stat.st_size
    doc.file_mtime = stat.st_mtime
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
