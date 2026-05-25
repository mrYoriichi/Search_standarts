"""Бизнес-логика модуля documents."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.modules.documents.models import Document
from backend.modules.documents.pipeline import run_pipeline
from backend.modules.documents.schemas import UploadItem
from pdf_processing.parser import make_document_id


# Папка, куда складываются загруженные PDF.
# Именно тут main.py ищет файл при вызове process(pdf_name) -> data/pdfs/{pdf_name}.pdf
PDF_STORAGE_DIR = Path("data/pdfs")


def list_documents(db: Session) -> list[Document]:
    """Все документы из библиотеки, упорядоченные по дате создания."""
    stmt = select(Document).order_by(Document.created_at)
    return list(db.scalars(stmt))


def create_documents_from_uploads(
    files: list[UploadFile],
    db: Session,
    executor: ThreadPoolExecutor,
) -> list[UploadItem]:
    """Принимает пачку PDF, для каждого нового запускает pipeline в фоне.

    Для существующих slug — пропускаем (action=skipped), чтобы случайная
    повторная загрузка не затёрла уже обработанный документ.
    """
    PDF_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    items: list[UploadItem] = []

    for upload in files:
        original_name = upload.filename or "untitled.pdf"
        title = Path(original_name).stem  # имя без расширения — для UI
        slug = make_document_id(original_name)

        existing = db.scalar(select(Document).where(Document.slug == slug))
        if existing is not None:
            items.append(UploadItem(slug=slug, title=existing.title, action="skipped"))
            continue

        # Сохраняем PDF на диск под именем {slug}.pdf — main.py смотрит сюда
        pdf_path = PDF_STORAGE_DIR / f"{slug}.pdf"
        with open(pdf_path, "wb") as f:
            f.write(upload.file.read())

        # Создаём запись и сразу коммитим — фоновый поток pipeline её читает
        doc = Document(slug=slug, title=title, status="processing")
        db.add(doc)
        db.commit()

        # Кидаем обработку в executor — вернёт управление сразу,
        # обработка пойдёт в одном из трёх потоков (или в очереди, если все заняты)
        executor.submit(run_pipeline, slug)

        items.append(UploadItem(slug=slug, title=title, action="created"))

    return items
