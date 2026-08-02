"""Бизнес-логика модуля documents."""

import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core import index_lock, index_store, library_cache
from backend.modules.documents.models import Document
from backend.modules.documents.pipeline import run_pipeline_locked
from common.jsonio import save_json_atomic


class DocumentBusyError(Exception):
    """Операция отклонена: документ сейчас обрабатывается пайплайном.

    Удаление/переиндексация/relink во время работы фонового pipeline дают
    гонку: пайплайн дописал бы артефакты уже ПОСЛЕ rmtree, и следующий
    «Skenovat» «усыновил» бы удалённый документ обратно (двойная оплата).
    """


def _ensure_not_processing(doc: Document) -> None:
    """Кидает DocumentBusyError, если документ сейчас в работе у пайплайна."""
    if doc.status == "processing":
        raise DocumentBusyError(
            f"Документ {doc.slug} сейчас индексируется — дождись конца обработки"
        )


def _artifact_dirs(slug: str, library_path: Path | None) -> list[Path]:
    """Папка артефактов документа в пуле .search_index его папки библиотеки.

    Список (а не один путь) — вызывающий код чистит все кандидаты подряд и не
    обязан знать, что кандидат сейчас один; отключённая папка даёт пустой
    список, а не ошибку.
    """
    if library_path is None:
        return []
    return [index_store.doc_dir(library_path, slug)]


def _doc_folder(paths: list[Path], slug: str) -> Path | None:
    """Папка библиотеки, которой принадлежит документ (по метке в slug)."""
    return index_store.resolve_folder(paths, slug)


def _ensure_folder_not_locked(library_path: Path | None) -> None:
    """Кидает DocumentBusyError, если папку сейчас индексирует ДРУГАЯ машина.

    delete/relink меняют общий .search_index — под чужим пайплайном rmtree/
    rename уронили бы его запись (оплаченный vision пропал бы). Лок здесь
    только проверяем, НЕ берём: acquire+done сбили бы счётчик документов,
    которые прямо сейчас индексирует наша собственная машина.
    """
    if library_path is None:
        return  # папка библиотеки неизвестна — координировать нечего
    busy = index_lock.holder(library_path)
    if busy is not None:
        raise DocumentBusyError(f"Složku právě indexuje jiný počítač: {busy}")


def list_documents(db: Session) -> list[Document]:
    """Все документы из библиотеки, упорядоченные по дате создания."""
    stmt = select(Document).order_by(Document.created_at)
    return list(db.scalars(stmt))


def reindex_document(
    db: Session,
    slug: str,
    paths: list[Path],
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
    _ensure_not_processing(doc)
    if doc.relative_path is None:
        raise ValueError(
            f"У документа {slug} нет relative_path — нужен Сканировать сначала"
        )

    library_path = _doc_folder(paths, slug)
    if library_path is None:
        raise ValueError(f"Папка документа {slug} не подключена")

    pdf_path = library_path / doc.relative_path
    if not pdf_path.exists():
        raise ValueError(f"PDF не найден в библиотеке: {pdf_path}")

    # Межмашинный лок папки — как при обычной индексации: без него reindex
    # писал бы в .search_index параллельно с другой машиной.
    busy = index_lock.acquire(library_path)
    if busy is not None:
        raise DocumentBusyError(f"Složku právě indexuje jiný počítač: {busy}")

    # Сносим старые артефакты — новые лягут в .search_index папки библиотеки.
    for artifacts_dir in _artifact_dirs(slug, library_path):
        if artifacts_dir.exists():
            shutil.rmtree(artifacts_dir)

    doc.status = "processing"
    doc.error_message = None
    db.commit()

    # Старые чанки документа уже удалены — убираем их из кеша сразу, не дожидаясь
    # конца переобработки (pipeline сбросит кеш ещё раз, когда документ снова готов).
    library_cache.invalidate()

    # Ленивый импорт: embeddings_index тянет openai/tiktoken.
    from indexing.embeddings_index import EMBEDDING_MODEL

    index_store.ensure_meta(library_path, EMBEDDING_MODEL)
    index_lock.register(library_path, 1)
    executor.submit(
        run_pipeline_locked,
        library_path,
        slug,
        str(pdf_path),
        index_store.doc_dir(library_path, slug),
    )
    return doc


def delete_document(db: Session, slug: str, paths: list[Path] | None = None) -> None:
    """Убирает документ из индекса: удаляет запись и наши артефакты.

    PDF в папке юзера НЕ трогаем — программа никогда не модифицирует
    файлы пользователя (см. PROJECT_STATE.md, принцип 16). Пишем только
    внутрь своей подпапки .search_index.
    """
    doc = db.scalar(select(Document).where(Document.slug == slug))
    if doc is None:
        raise ValueError(f"Документ {slug} не найден")
    _ensure_not_processing(doc)

    library_path = _doc_folder(paths or [], slug)
    _ensure_folder_not_locked(library_path)
    for artifacts_dir in _artifact_dirs(slug, library_path):
        if artifacts_dir.exists():
            shutil.rmtree(artifacts_dir)

    db.delete(doc)
    db.commit()
    library_cache.invalidate()  # документ исчез с диска — обновить кеш


def toggle_pin(db: Session, slug: str) -> Document:
    """Переключает закреплённость документа. Бросает ValueError, если не найден."""
    doc = db.scalar(select(Document).where(Document.slug == slug))
    if doc is None:
        raise ValueError(f"Документ {slug} не найден")
    doc.pinned = not doc.pinned
    db.commit()
    return doc


def relink_document(
    db: Session, old_slug: str, new_slug: str, paths: list[Path] | None = None
) -> Document:
    """Переносит существующий индекс со старого slug на новый — для переименования файла.

    Юзер переименовал PDF в папке библиотеки. Чтобы не платить за повторный
    vision LLM ($$$ за тот же документ), переносим уже готовые чанки и
    эмбеддинги на новое имя.

    Шаги:
    1. Переименовать папку артефактов {old_slug}/ -> {new_slug}/ в том пуле,
       где она лежит (.search_index папки библиотеки)
    2. В chunks.json заменить document_id и префикс chunk_id со старого на новый
    3. В embeddings.json заменить префикс chunk_id
    4. Обновить Document.slug в БД
    """
    if old_slug == new_slug:
        raise ValueError("old_slug и new_slug совпадают")

    doc = db.scalar(select(Document).where(Document.slug == old_slug))
    if doc is None:
        raise ValueError(f"Документ {old_slug} не найден в БД")
    _ensure_not_processing(doc)

    conflicting = db.scalar(select(Document).where(Document.slug == new_slug))
    if conflicting is not None:
        raise ValueError(f"Документ с slug {new_slug} уже существует")

    # Индекс переносим внутри того пула, где он реально лежит.
    library_path = _doc_folder(paths or [], old_slug)
    _ensure_folder_not_locked(library_path)
    old_dir = next(
        (d for d in _artifact_dirs(old_slug, library_path) if d.exists()), None
    )
    if old_dir is None:
        raise ValueError(f"Папка артефактов {old_slug} не найдена на диске")
    new_dir = old_dir.parent / new_slug
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
        save_json_atomic(chunks_path, chunks)

    # 3. embeddings.json: chunk_id внутри items.
    emb_path = new_dir / "embeddings.json"
    if emb_path.exists():
        with open(emb_path, encoding="utf-8") as f:
            emb = json.load(f)
        for item in emb.get("items", []):
            item["chunk_id"] = _replace_prefix(item["chunk_id"], old_slug, new_slug)
        save_json_atomic(emb_path, emb)

    # 4. Обновляем slug в БД.
    doc.slug = new_slug
    db.commit()
    library_cache.invalidate()  # document_id/chunk_id поменялись — обновить кеш
    return doc


def _replace_prefix(value: str, old: str, new: str) -> str:
    """Заменяет старый префикс на новый. Если префикса нет — возвращает как есть."""
    if value.startswith(old):
        return new + value[len(old) :]
    return value
