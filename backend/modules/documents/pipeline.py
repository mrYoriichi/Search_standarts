"""Pipeline обработки одного PDF: main -> describe -> chunk -> index.

Вызывается из ThreadPoolExecutor (фоновый поток), не из HTTP-запроса.
Поэтому сессию БД открываем сами через SessionLocal() и закрываем в finally —
FastAPI-зависимости здесь не работают.
"""
import json
import logging
from pathlib import Path

from sqlalchemy import select

from backend.core import library_cache
from backend.core.database import SessionLocal
from backend.modules.documents.models import Document
from backend.modules.telemetry.service import track_event


logger = logging.getLogger(__name__)


def run_pipeline(slug: str, pdf_path: str | None = None) -> None:
    """Прогоняет полный пайплайн для одного документа.

    slug — id документа, совпадает с именем папки в data/raw_data/{slug}/.
    pdf_path — полный путь к PDF. Если не задан, main.py возьмёт по старой
    логике из data/pdfs/{slug}.pdf (upload-flow). Сканирование папки
    библиотеки передаёт сюда путь к PDF прямо из папки юзера.

    На любой ошибке: status='failed' + текст ошибки в Document.error_message.
    На успехе: status='ready', error_message=None.
    """
    # Lazy import — Docling и transformers весят и грузятся секунд 20-30.
    # Если импортировать наверху, всё это тянется при старте сервера
    # и при каждом --reload, что превращает разработку в пытку.
    # Здесь же грузится только при первом реальном вызове pipeline.
    import main as parser_step
    import describe as describe_step
    import chunk as chunk_step
    import index as index_step

    # Импорт здесь (не наверху) — избегаем цикла с модулем settings.
    from backend.modules.settings import service as settings_service

    db = SessionLocal()
    try:
        # Vision-модель — рычаг стоимости, юзер выбирает в «Knihovna». Читаем на
        # старте обработки документа, чтобы применить актуальный выбор.
        vision_model = settings_service.get_vision_model(db)
        try:
            parser_step.process(slug, pdf_path=pdf_path)
            describe_step.process(slug, vision_model=vision_model)
            chunk_step.process(slug)
            index_step.process(slug)
        except Exception as exc:
            logger.exception("Pipeline для %s упал", slug)
            doc = db.scalar(select(Document).where(Document.slug == slug))
            if doc is not None:
                doc.status = "failed"
                doc.error_message = f"{type(exc).__name__}: {exc}"
                db.commit()
            track_event("pdf_failed", error_type=type(exc).__name__)
            return

        # Берём настоящий заголовок документа из descriptions.json
        # (его проставил describe_step). При загрузке у нас был только
        # filename — теперь подменим на нормальное название.
        descriptions_path = Path("data/raw_data") / slug / "descriptions.json"
        with open(descriptions_path, encoding="utf-8") as f:
            real_title = json.load(f).get("document_title")

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
        chunks_path = Path("data/raw_data") / slug / "chunks.json"
        chunks_count: int | None = None
        try:
            with open(chunks_path, encoding="utf-8") as f:
                chunks_count = len(json.load(f))
        except Exception:  # pylint: disable=broad-except
            pass
        track_event("pdf_indexed", chunks_count=chunks_count)
    finally:
        db.close()
