"""Pipeline обработки одного PDF: main -> describe -> chunk -> index.

Вызывается из ThreadPoolExecutor (фоновый поток), не из HTTP-запроса.
Поэтому сессию БД открываем сами через SessionLocal() и закрываем в finally —
FastAPI-зависимости здесь не работают.
"""

import json
import logging
import tempfile
from pathlib import Path

from sqlalchemy import select

from backend.core import index_lock, library_cache, progress
from backend.core.database import SessionLocal
from backend.core.errors import classify_pipeline_error
from backend.modules.documents.models import Document
from backend.modules.telemetry.service import track_event


logger = logging.getLogger(__name__)


def run_pipeline_locked(
    library_path: Path, slug: str, pdf_path: str | None, doc_dir: Path
) -> None:
    """Пайплайн под межмашинным локом папки (см. backend/core/index_lock.py).

    Освежает лок в начале, отмечает документ завершённым в конце (последний
    документ папки снимает лок). ВСЕ пути, пишущие в .search_index — запуск
    кнопкой, переиндексация, возобновление после падения, — обязаны идти
    через эту обёртку, иначе лок не живёт и другая машина зайдёт параллельно.
    """
    try:
        index_lock.refresh(library_path)
        run_pipeline(slug, pdf_path, doc_dir)
    finally:
        index_lock.done(library_path)


def run_pipeline(slug: str, pdf_path: str | None, doc_dir: Path) -> None:
    """Прогоняет полный пайплайн для одного документа.

    slug — id документа, совпадает с именем папки артефактов.
    pdf_path — полный путь к PDF в папке юзера.
    doc_dir — папка артефактов: `<папка библиотеки>/.search_index/{slug}`.
    Оба задаёт вызывающий код — дефолтов нет намеренно: молчаливый фолбэк на
    локальный пул уводил документы мимо папки библиотеки.

    Скриншоты страниц живут во ВРЕМЕННОЙ локальной папке: нужны только
    vision-шагу, в артефактах не хранятся (и не ездят на сетевой диск).

    На любой ошибке: status='failed' + текст ошибки в Document.error_message.
    На успехе: status='ready', error_message=None.
    """
    # Lazy import — Docling и transformers весят и грузятся секунд 20-30.
    # Если импортировать наверху, всё это тянется при старте сервера
    # и при каждом --reload, что превращает разработку в пытку.
    # Здесь же грузится только при первом реальном вызове pipeline.
    from pipeline import chunk as chunk_step
    from pipeline import describe as describe_step
    from pipeline import embed as index_step
    from pipeline import parse as parser_step

    # Импорт здесь (не наверху) — избегаем цикла с модулем settings.
    from backend.modules.settings import service as settings_service

    db = SessionLocal()
    try:
        # Vision-модель — рычаг стоимости, юзер выбирает в «Knihovna». Читаем на
        # старте обработки документа, чтобы применить актуальный выбор.
        vision_model = settings_service.get_vision_model(db)
        describe_images = settings_service.get_describe_images(db)
        try:
            with tempfile.TemporaryDirectory(prefix=f"ss_pages_{slug}_") as tmp:
                pages_dir = Path(tmp)
                progress.set_progress(slug, "čtení PDF…")
                # document_id=slug: в артефакты должен попасть scoped-slug
                # ({folder_id}__{файл}) из БД, а не id из имени файла — иначе
                # фильтр «Kde hledat» не совпадёт ни с одним чанком.
                parser_step.process(
                    slug,
                    pdf_path=pdf_path,
                    doc_dir=doc_dir,
                    document_id=slug,
                    pages_dir=pages_dir,
                )
                progress.set_progress(slug, "popis obrázků…")
                describe_step.process(
                    slug,
                    vision_model=vision_model,
                    doc_dir=doc_dir,
                    pages_dir=pages_dir,
                    pdf_path=pdf_path,
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
            progress.set_progress(slug, "indexace…")
            index_step.process(slug, doc_dir=doc_dir)
        except Exception as exc:
            logger.exception("Pipeline для %s упал", slug)
            doc = db.scalar(select(Document).where(Document.slug == slug))
            if doc is not None:
                doc.status = "failed"
                doc.error_message = classify_pipeline_error(exc)
                db.commit()
            track_event("pdf_failed", error_type=type(exc).__name__)
            return

        # Берём настоящий заголовок документа из descriptions.json
        # (его проставил describe_step). При загрузке у нас был только
        # filename — теперь подменим на нормальное название. Ошибка чтения
        # НЕ должна ронять пост-обработку: этот код вне try выше, необработанное
        # исключение молча съел бы executor и документ завис бы в processing.
        descriptions_path = doc_dir / "descriptions.json"
        real_title = None
        try:
            with open(descriptions_path, encoding="utf-8") as f:
                real_title = json.load(f).get("document_title")
        except (OSError, json.JSONDecodeError):
            logger.warning("Не смог прочитать заголовок из %s", descriptions_path)

        doc = db.scalar(select(Document).where(Document.slug == slug))
        if doc is not None:
            if real_title:
                doc.title = real_title
            doc.status = "ready"
            doc.error_message = None
            db.commit()

        # Появились новые чанки/эмбеддинги на диске — сбрасываем кеш библиотеки,
        # чтобы следующий вопрос увидел свежий документ.
        library_cache.invalidate()

        # Считаем число чанков как косвенный размер документа — слать имя файла
        # нельзя (это уже Уровень 2 / персональные данные).
        chunks_path = doc_dir / "chunks.json"
        chunks_count: int | None = None
        try:
            with open(chunks_path, encoding="utf-8") as f:
                chunks_count = len(json.load(f))
        except Exception:  # pylint: disable=broad-except
            pass
        track_event("pdf_indexed", chunks_count=chunks_count)
    finally:
        progress.clear_progress(slug)
        db.close()
