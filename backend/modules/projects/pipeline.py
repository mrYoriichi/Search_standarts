"""Пайплайн обработки документов архива проектов.

Все документы (TZ, статика, чертежи) идут через общий по-страничный
пайплайн норм (main→describe→chunk→index): роутер сам решает, что
проза (Docling), а что чертёж (OCR + vision-паспорт). Специфика архива —
только id чанков от slug `{проект}__{файл}`, проект в «шапке» чанка и
хранилище PROJECTS_DATA_DIR.
"""

import json
import logging
from pathlib import Path

from sqlalchemy import select

from backend.core import progress
from backend.core.database import SessionLocal
from backend.core.errors import classify_pipeline_error
from backend.core.paths import PROJECTS_DATA_DIR
from backend.modules.projects.models import ProjectDocument

from jsonio import save_json_atomic


logger = logging.getLogger(__name__)


def _prefix_project_context(doc_dir: Path, project: str) -> None:
    """Добавляет проект в document_title всех чанков (перед эмбеддингом).

    document_title входит в «шапку» чанка при индексации — так чанк
    «zatížení větrem» из статики ищется в контексте своего проекта/объекта.
    """
    chunks_path = doc_dir / "chunks.json"
    chunks = json.loads(chunks_path.read_text(encoding="utf-8"))
    for chunk in chunks:
        title = chunk.get("document_title", "")
        if not title.startswith(project):
            chunk["document_title"] = f"{project} — {title}" if title else project
    save_json_atomic(chunks_path, chunks)


def process_text_document(
    slug: str,
    pdf_path: Path,
    project: str,
    vision_model: str,
    describe_images: bool = True,
) -> None:
    """Текстовый документ архива (TZ, статика): существующий пайплайн норм.

    Docling → vision-описания картинок (модели/эпюры в статике — тоже сюда)
    → нарезка по заголовкам → проект в шапку → эмбеддинги.
    Всё пишется в PROJECTS_DATA_DIR/{slug}/, id чанков — от нашего slug.
    describe_images=False → режим «Без LLM»: vision пропускается.
    """
    # Lazy import — Docling тяжёлый, грузим только при реальной обработке
    # (та же причина, что в documents/pipeline.py).
    import main as parser_step
    import describe as describe_step
    import chunk as chunk_step
    import index as index_step

    doc_dir = PROJECTS_DATA_DIR / slug
    progress.set_progress(slug, "čtení PDF…")
    parser_step.process(slug, pdf_path=str(pdf_path), doc_dir=doc_dir, document_id=slug)
    progress.set_progress(slug, "popis obrázků…")
    describe_step.process(
        slug,
        vision_model=vision_model,
        doc_dir=doc_dir,
        pdf_path=str(pdf_path),
        describe_images=describe_images,
        on_progress=lambda done, total: progress.set_progress(
            slug, f"popis obrázků: strana {done}/{total}"
        ),
        on_drawing_progress=lambda done, total: progress.set_progress(
            slug, f"popis výkresů: strana {done}/{total}"
        ),
    )
    progress.set_progress(slug, "řezání na části…")
    chunk_step.process(slug, doc_dir=doc_dir)
    _prefix_project_context(doc_dir, project)
    progress.set_progress(slug, "indexace…")
    index_step.process(slug, doc_dir=doc_dir)


def run_project_pipeline(slug: str, pdf_path: str) -> None:
    """Полная обработка одного документа архива (вызов из ThreadPoolExecutor).

    Статусы: processing → ready | error (+ текст ошибки в error).
    Сессию БД открываем сами — FastAPI-зависимости в фоновом потоке не работают.
    """
    from backend.modules.settings import service as settings_service

    db = SessionLocal()
    try:
        doc = db.scalar(select(ProjectDocument).where(ProjectDocument.slug == slug))
        if doc is None:
            logger.error("run_project_pipeline: slug %s не найден в БД", slug)
            return
        doc.status = "processing"
        db.commit()

        vision_model = settings_service.get_vision_model(db)
        describe_images = settings_service.get_describe_images(db)
        try:
            process_text_document(
                slug=slug,
                pdf_path=Path(pdf_path),
                project=doc.project,
                vision_model=vision_model,
                describe_images=describe_images,
            )
        except Exception as exc:
            logger.exception("Пайплайн архива для %s упал", slug)
            doc.status = "error"
            doc.error = classify_pipeline_error(exc)
            db.commit()
            return

        doc.status = "ready"
        doc.error = None
        db.commit()

        # Новые чанки/эмбеддинги на диске — сбрасываем кеш, чтобы следующий
        # вопрос увидел свежий документ (пул архива влит в общий кеш поиска).
        from backend.core import library_cache

        library_cache.invalidate()
    finally:
        progress.clear_progress(slug)
        db.close()
