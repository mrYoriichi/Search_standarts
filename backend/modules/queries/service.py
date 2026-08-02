"""Бизнес-логика «Вопрос → Ответ».

Тонкая обёртка над существующим кодом (`ask.py`, `search/*`, `indexing/*`):
загрузить библиотеку → отфильтровать → гибридный поиск → LLM → запись в БД.

Никакого HTTP здесь нет — функцию `ask` можно вызывать из роутера, из тестов,
из будущего AI-агента-оркестратора.
"""

import logging
import time
from pathlib import Path

from sqlalchemy.orm import Session

from search.library import filter_library
from indexing.bm25_index import build_bm25_from_tokens
from common.pricing import model_cost
from search.expand import expand_query
from search.lang_detect import corpus_languages
from search.hybrid import search_by_mode
from search.answer import generate_answer

from backend.core import library_cache
from backend.core.ui_messages import msg
from backend.modules.queries.models import QueryLog
from backend.modules.queries.schemas import AskResponse, Source, UsedChunk
from backend.modules.telemetry.service import track_event


logger = logging.getLogger(__name__)

# Сильный поиск: максимум страниц-картинок в запросе к отвечающей LLM.
# Каждая страница — vision-токены; топ-3 покрывает типовой вопрос
# «что на этом листе», не раздувая стоимость и время ответа.
STRONG_MAX_PAGES = 3


class NoSearchableDocumentsError(Exception):
    """Фильтр не совпал ни с одним документом.

    Типовая причина: юзер держал вкладку открытой, документы из его выбора
    успели удалиться/переименоваться — фронт прислал устаревшие document_ids.
    Без этой проверки пустой корпус ронял BM25 (ZeroDivisionError → HTTP 500).
    """


def collect_page_refs(
    top_chunks: list[dict], limit: int = STRONG_MAX_PAGES
) -> list[tuple[str, int]]:
    """Страницы топ-выдачи для сильного поиска: список (slug, страница).

    Идём по чанкам в порядке релевантности, внутри чанка — по его страницам;
    дубли (slug, страница) убираем, всего не больше limit.
    """
    refs: list[tuple[str, int]] = []
    seen: set[tuple[str, int]] = set()
    for chunk in top_chunks:
        slug = chunk.get("document_id", "")
        for page in chunk.get("pages", []):
            key = (slug, page)
            if key in seen:
                continue
            seen.add(key)
            refs.append(key)
            if len(refs) >= limit:
                return refs
    return refs


def _render_page_b64(pdf_path: Path, page_number: int) -> str | None:
    """PNG страницы PDF в base64 — на лету, без записи на диск.

    Best-effort: любой сбой (битый PDF, страницы нет) → None, сильный
    поиск просто продолжит без этой картинки.
    """
    import base64
    import io

    import pypdfium2 as pdfium

    from pdf_processing.drawing import RENDER_MAX_SIDE_PX
    from pdf_processing.pdfium_lock import PDFIUM_LOCK

    try:
        with PDFIUM_LOCK:
            doc = pdfium.PdfDocument(pdf_path)
            try:
                page = doc[page_number - 1]
                width, height = page.get_size()
                scale = RENDER_MAX_SIDE_PX / max(width, height)
                pil = page.render(scale=scale).to_pil()
            finally:
                doc.close()
        buf = io.BytesIO()
        pil.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("utf-8")
    except Exception:
        logger.warning(
            "Сильный поиск: не отрендерилась страница %s из %s", page_number, pdf_path
        )
        return None


def _build_page_images(db: Session, top_chunks: list[dict]) -> list[dict]:
    """Снимки страниц топ-источников: [{"label": "документ, s. N", "b64": ...}].

    Путь к PDF резолвим по всем пулам (библиотека + архив, см.
    resolve_pdf_by_slug); документ без PDF на диске или несуществующая
    страница просто пропускаются — ответ пойдёт по тексту.
    """
    from backend.modules.library.service import resolve_pdf_by_slug

    titles = {c.get("document_id", ""): c.get("document_title", "") for c in top_chunks}
    pdf_paths: dict[str, Path | None] = {}
    images: list[dict] = []
    for slug, page in collect_page_refs(top_chunks):
        if slug not in pdf_paths:
            pdf_paths[slug] = resolve_pdf_by_slug(db, slug)
        pdf_path = pdf_paths[slug]
        if pdf_path is None:
            continue
        b64 = _render_page_b64(pdf_path, page)
        if b64 is None:
            continue
        images.append({"label": f"{titles.get(slug, slug)}, s. {page}", "b64": b64})
    return images


def ask(
    question: str,
    document_ids: list[str] | None,
    db: Session,
    mode: str = "hybrid",
    answer_model: str = "gpt-5.4-mini",
    expand: bool = True,
    strong: bool = False,
    answer_language: str | None = None,
) -> AskResponse:
    """Главная функция: вопрос → ответ + источники + id записи в QueryLog.

    document_ids=None — искать по всей библиотеке.
    mode — режим поиска (hybrid / vector / keyword), см. search.hybrid.
    answer_model — модель генерации ответа (gpt-5.4-mini / gpt-5.5).
    expand — расширять ли запрос через LLM перед поиском (диакритика/синонимы).
    strong — сильный поиск: приложить к ответу снимки страниц топ-источников
    (тяжёлые вопросы по чертежам/таблицам; дороже и медленнее).
    answer_language — язык ответа LLM (cs/en/de); None — сохранённая
    настройка юзера (см. settings.get_answer_language).
    """
    started_at = time.perf_counter()

    # Библиотека лежит в памяти (см. backend/core/library_cache.py) — с диска
    # читаем только при первом вопросе и после изменений библиотеки. Чанки и
    # токены берём одним вызовом — они гарантированно одного поколения кеша.
    chunks, embeddings_index, tokens_by_id = library_cache.get_library_with_tokens()

    if document_ids:
        chunks, embeddings_index = filter_library(
            chunks, embeddings_index, set(document_ids)
        )
        if not chunks:
            raise NoSearchableDocumentsError(msg("lib.stale_selection"))

    # Расширяем запрос для поиска (диакритика, термины, синонимы), но ответ
    # генерим по ОРИГИНАЛЬНОМУ вопросу — чтобы отвечать на то, что спросил юзер.
    # Расширение можно отключить галочкой (expand=False) — тогда ищем как есть.
    # Языки корпуса считаем по УЖЕ отфильтрованным чанкам: если юзер ищет
    # только в чешской папке, английские термины в запросе не нужны.
    search_query = (
        expand_query(question, corpus_languages(chunks)) if expand else question
    )

    # BM25 собираем из закешированных токенов текущего набора чанков (с учётом
    # фильтра) — IDF считается по этому же набору, как и раньше.
    tokenized = [tokens_by_id[c["chunk_id"]] for c in chunks]
    chunk_ids = [c["chunk_id"] for c in chunks]
    bm25 = build_bm25_from_tokens(tokenized, chunk_ids)
    found_ids = search_by_mode(bm25, embeddings_index, search_query, mode)

    chunks_by_id = {c["chunk_id"]: c for c in chunks}
    # Вектора-сироты (embeddings.json из другого поколения, чем chunks.json)
    # пропускаем, а не роняем весь вопрос KeyError'ом — №2 аудита.
    orphan_ids = [cid for cid in found_ids if cid not in chunks_by_id]
    if orphan_ids:
        logger.warning(
            "Поиск вернул id без чанков (индекс рассинхронизирован, "
            "нужна переиндексация): %s",
            orphan_ids,
        )
    top_chunks = [chunks_by_id[cid] for cid in found_ids if cid in chunks_by_id]

    # Сильный поиск: рендерим страницы топ-источников и отдаём их картинками
    # в отвечающую LLM — она «видит» чертёж/таблицу, а не только текст/OCR.
    page_images = _build_page_images(db, top_chunks) if strong else None

    if answer_language is None:
        # Настройка живёт в профиле; запрос может переопределить её явно
        # (API agent-ready: агенту не нужно трогать настройки).
        from backend.modules.settings import service as settings_service

        answer_language = settings_service.get_answer_language(db)

    # Время генерации ответа меряем отдельно — чтобы сравнивать скорость моделей.
    gen_start = time.perf_counter()
    result = generate_answer(
        question,
        top_chunks,
        model=answer_model,
        page_images=page_images,
        answer_language=answer_language,
    )
    answer_ms = int((time.perf_counter() - gen_start) * 1000)

    # Стоимость считаем только по ответному LLM-вызову — он доминирует.
    # Цена берётся из таблицы по имени модели (pricing.MODEL_PRICES_PER_M).
    cost_usd = model_cost(
        answer_model, result["prompt_tokens"], result["completion_tokens"]
    )
    duration_ms = int((time.perf_counter() - started_at) * 1000)

    log = QueryLog(
        question=question,
        answer=result["answer"],
        duration_ms=duration_ms,
        cost_usd=cost_usd,
    )
    db.add(log)
    db.commit()
    db.refresh(log)

    # Анонимная техническая телеметрия: цифры, без текста вопроса/ответа.
    track_event(
        "query_asked",
        duration_ms=duration_ms,
        cost_usd=cost_usd,
        scope="filtered" if document_ids else "all",
        mode=mode,
        answer_model=answer_model,
        answer_ms=answer_ms,
        chunks_searched=len(chunks),
        sources_returned=len(result["sources"]),
        strong=strong,
        images_sent=len(page_images or []),
    )

    return AskResponse(
        answer=result["answer"],
        sources=[Source(**s) for s in result["sources"]],
        related_sources=[Source(**s) for s in result["related_sources"]],
        used_chunks=[UsedChunk(**c) for c in result["used_chunks"]],
        query_log_id=log.id,
        search_query=search_query,
        answer_model=answer_model,
        answer_ms=answer_ms,
    )
