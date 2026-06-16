"""Бизнес-логика «Вопрос → Ответ».

Тонкая обёртка над существующим кодом (`ask.py`, `search/*`, `indexing/*`):
загрузить библиотеку → отфильтровать → гибридный поиск → LLM → запись в БД.

Никакого HTTP здесь нет — функцию `ask` можно вызывать из роутера, из тестов,
из будущего AI-агента-оркестратора.
"""

import time

from sqlalchemy.orm import Session

from ask import filter_library
from indexing.bm25_index import build_bm25_from_tokens
from pricing import model_cost
from search.expand import expand_query
from search.hybrid import search_by_mode
from search.answer import generate_answer

from backend.core import library_cache
from backend.modules.queries.models import QueryLog
from backend.modules.queries.schemas import AskResponse, Source, UsedChunk
from backend.modules.telemetry.service import track_event


def ask(
    question: str,
    document_ids: list[str] | None,
    db: Session,
    mode: str = "hybrid",
    answer_model: str = "gpt-5.4-mini",
) -> AskResponse:
    """Главная функция: вопрос → ответ + источники + id записи в QueryLog.

    document_ids=None — искать по всей библиотеке.
    mode — режим поиска (hybrid / vector / keyword), см. search.hybrid.
    answer_model — модель генерации ответа (gpt-5.4-mini / gpt-5.5).
    """
    started_at = time.perf_counter()

    # Библиотека лежит в памяти (см. backend/core/library_cache.py) — с диска
    # читаем только при первом вопросе и после изменений библиотеки.
    chunks, embeddings_index = library_cache.get_library()
    tokens_by_id = library_cache.get_tokens()

    if document_ids:
        chunks, embeddings_index = filter_library(
            chunks, embeddings_index, set(document_ids)
        )

    # Расширяем запрос для поиска (диакритика, термины, синонимы), но ответ
    # генерим по ОРИГИНАЛЬНОМУ вопросу — чтобы отвечать на то, что спросил юзер.
    search_query = expand_query(question)

    # BM25 собираем из закешированных токенов текущего набора чанков (с учётом
    # фильтра) — IDF считается по этому же набору, как и раньше.
    tokenized = [tokens_by_id[c["chunk_id"]] for c in chunks]
    chunk_ids = [c["chunk_id"] for c in chunks]
    bm25 = build_bm25_from_tokens(tokenized, chunk_ids)
    found_ids = search_by_mode(bm25, embeddings_index, search_query, mode)

    chunks_by_id = {c["chunk_id"]: c for c in chunks}
    top_chunks = [chunks_by_id[chunk_id] for chunk_id in found_ids]

    # Время генерации ответа меряем отдельно — чтобы сравнивать скорость моделей.
    gen_start = time.perf_counter()
    result = generate_answer(question, top_chunks, model=answer_model)
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
