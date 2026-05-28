"""Бизнес-логика «Вопрос → Ответ».

Тонкая обёртка над существующим кодом (`ask.py`, `search/*`, `indexing/*`):
загрузить библиотеку → отфильтровать → гибридный поиск → LLM → запись в БД.

Никакого HTTP здесь нет — функцию `ask` можно вызывать из роутера, из тестов,
из будущего AI-агента-оркестратора.
"""

import time

from sqlalchemy.orm import Session

from ask import filter_library
from indexing.bm25_index import build_bm25_index
from pricing import answer_cost
from search.hybrid import hybrid_search
from search.answer import generate_answer

from backend.core import library_cache
from backend.modules.queries.models import QueryLog
from backend.modules.queries.schemas import AskResponse, Source
from backend.modules.telemetry.service import track_event


# Тот же top_k, что и в CLI-сценарии ask.py
TOP_K = 5


def ask(
    question: str,
    document_ids: list[str] | None,
    db: Session,
) -> AskResponse:
    """Главная функция: вопрос → ответ + источники + id записи в QueryLog.

    document_ids=None — искать по всей библиотеке.
    """
    started_at = time.perf_counter()

    # Библиотека лежит в памяти (см. backend/core/library_cache.py) — с диска
    # читаем только при первом вопросе и после изменений библиотеки.
    chunks, embeddings_index = library_cache.get_library()

    if document_ids:
        chunks, embeddings_index = filter_library(
            chunks, embeddings_index, set(document_ids)
        )

    bm25 = build_bm25_index(chunks)
    found = hybrid_search(bm25, embeddings_index, question, top_k=TOP_K)

    chunks_by_id = {c["chunk_id"]: c for c in chunks}
    top_chunks = [chunks_by_id[chunk_id] for chunk_id, _ in found]

    result = generate_answer(question, top_chunks)

    # Стоимость считаем только по ответному LLM-вызову — он доминирует.
    # Эмбеддинг запроса (~20-50 токенов) даёт ~$0.000005 за запрос, игнорируем.
    cost_usd = answer_cost(
        result["prompt_tokens"], result["completion_tokens"]
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
        chunks_searched=len(chunks),
        sources_returned=len(result["sources"]),
    )

    return AskResponse(
        answer=result["answer"],
        sources=[Source(**s) for s in result["sources"]],
        query_log_id=log.id,
    )
