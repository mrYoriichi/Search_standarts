"""Бизнес-логика модуля documents."""

import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.modules.documents.models import Document
from backend.modules.documents.pipeline import run_pipeline
from backend.modules.documents.schemas import UploadItem
from pdf_processing.parser import make_document_id


# Корень обработанных артефактов: chunks.json, embeddings.json, pages/...
RAW_DATA_DIR = Path("data/raw_data")


# Папка, куда складываются загруженные PDF.
# Именно тут main.py ищет файл при вызове process(pdf_name) -> data/pdfs/{pdf_name}.pdf
PDF_STORAGE_DIR = Path("data/pdfs")


def list_documents(db: Session) -> list[Document]:
    """Все документы из библиотеки, упорядоченные по дате создания."""
    stmt = select(Document).order_by(Document.created_at)
    return list(db.scalars(stmt))


def reindex_document(
    db: Session,
    slug: str,
    library_path: Path,
    executor: ThreadPoolExecutor,
) -> Document:
    """Полностью переобрабатывает документ: удаляет старые артефакты и запускает pipeline.

    Нужно, когда юзер заменил содержимое PDF (имя файла осталось то же).
    Старые чанки/эмбеддинги тогда устарели — выбрасываем их и собираем заново.
    Сам PDF в библиотеке НЕ трогаем.
    """
    doc = db.scalar(select(Document).where(Document.slug == slug))
    if doc is None:
        raise ValueError(f"Документ {slug} не найден")
    if doc.relative_path is None:
        raise ValueError(
            f"У документа {slug} нет relative_path — нужен Сканировать сначала"
        )

    pdf_path = library_path / doc.relative_path
    if not pdf_path.exists():
        raise ValueError(f"PDF не найден в библиотеке: {pdf_path}")

    artifacts_dir = RAW_DATA_DIR / slug
    if artifacts_dir.exists():
        shutil.rmtree(artifacts_dir)

    doc.status = "processing"
    doc.error_message = None
    db.commit()

    executor.submit(run_pipeline, slug, str(pdf_path))
    return doc


def delete_document(db: Session, slug: str) -> None:
    """Убирает документ из индекса: удаляет запись и наши артефакты.

    PDF в папке юзера НЕ трогаем — программа никогда не модифицирует
    файлы пользователя (см. PROJECT_STATE.md, принцип 16).
    """
    doc = db.scalar(select(Document).where(Document.slug == slug))
    if doc is None:
        raise ValueError(f"Документ {slug} не найден")

    artifacts_dir = RAW_DATA_DIR / slug
    if artifacts_dir.exists():
        shutil.rmtree(artifacts_dir)

    db.delete(doc)
    db.commit()


def toggle_pin(db: Session, slug: str) -> Document:
    """Переключает закреплённость документа. Бросает ValueError, если не найден."""
    doc = db.scalar(select(Document).where(Document.slug == slug))
    if doc is None:
        raise ValueError(f"Документ {slug} не найден")
    doc.pinned = not doc.pinned
    db.commit()
    return doc


def relink_document(db: Session, old_slug: str, new_slug: str) -> Document:
    """Переносит существующий индекс со старого slug на новый — для переименования файла.

    Юзер переименовал PDF в папке библиотеки. Чтобы не платить за повторный
    vision LLM ($$$ за тот же документ), переносим уже готовые чанки и
    эмбеддинги на новое имя.

    Шаги:
    1. Переименовать data/raw_data/{old_slug}/ -> {new_slug}/
    2. В chunks.json заменить document_id и префикс chunk_id со старого на новый
    3. В embeddings.json заменить префикс chunk_id
    4. Обновить Document.slug в БД
    """
    if old_slug == new_slug:
        raise ValueError("old_slug и new_slug совпадают")

    doc = db.scalar(select(Document).where(Document.slug == old_slug))
    if doc is None:
        raise ValueError(f"Документ {old_slug} не найден в БД")

    conflicting = db.scalar(select(Document).where(Document.slug == new_slug))
    if conflicting is not None:
        raise ValueError(f"Документ с slug {new_slug} уже существует")

    old_dir = RAW_DATA_DIR / old_slug
    new_dir = RAW_DATA_DIR / new_slug
    if not old_dir.exists():
        raise ValueError(f"Папка {old_dir} не найдена на диске")
    if new_dir.exists():
        raise ValueError(f"Папка {new_dir} уже существует — конфликт")

    # 1. Переименовываем папку с артефактами.
    old_dir.rename(new_dir)

    # 2. chunks.json: подменяем document_id и префикс chunk_id.
    chunks_path = new_dir / "chunks.json"
    if chunks_path.exists():
        with open(chunks_path, encoding="utf-8") as f:
            chunks = json.load(f)
        for chunk in chunks:
            chunk["document_id"] = new_slug
            chunk["chunk_id"] = _replace_prefix(chunk["chunk_id"], old_slug, new_slug)
        with open(chunks_path, "w", encoding="utf-8") as f:
            json.dump(chunks, f, ensure_ascii=False, indent=2)

    # 3. embeddings.json: chunk_id внутри items.
    emb_path = new_dir / "embeddings.json"
    if emb_path.exists():
        with open(emb_path, encoding="utf-8") as f:
            emb = json.load(f)
        for item in emb.get("items", []):
            item["chunk_id"] = _replace_prefix(item["chunk_id"], old_slug, new_slug)
        with open(emb_path, "w", encoding="utf-8") as f:
            json.dump(emb, f, ensure_ascii=False, indent=2)

    # 4. Обновляем slug в БД.
    doc.slug = new_slug
    db.commit()
    return doc


def _replace_prefix(value: str, old: str, new: str) -> str:
    """Заменяет старый префикс на новый. Если префикса нет — возвращает как есть."""
    if value.startswith(old):
        return new + value[len(old):]
    return value


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
