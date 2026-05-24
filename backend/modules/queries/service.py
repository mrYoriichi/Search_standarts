"""Бизнес-логика «Вопрос → Ответ».

Тонкая обёртка над существующим кодом (`ask.py`, `search/*`, `indexing/*`):
загрузить библиотеку → отфильтровать → гибридный поиск → LLM → запись в БД.

Никакого HTTP здесь нет — функцию `ask` можно вызывать из роутера, из тестов,
из будущего AI-агента-оркестратора.
"""

from pathlib import Path

from sqlalchemy.orm import Session

from ask import load_library, filter_library
from indexing.bm25_index import build_bm25_index
from search.hybrid import hybrid_search
from search.answer import generate_answer

from backend.modules.queries.models import QueryLog
from backend.modules.queries.schemas import AskResponse, Source


# Тот же top_k, что и в CLI-сценарии ask.py
TOP_K = 5
DATA_ROOT = Path("data/raw_data")


def ask(
    question: str,
    document_ids: list[str] | None,
    db: Session,
) -> AskResponse:
    """Главная функция: вопрос → ответ + источники + id записи в QueryLog.

    document_ids=None — искать по всей библиотеке.
    """
    chunks, embeddings_index = load_library(DATA_ROOT)

    if document_ids:
        chunks, embeddings_index = filter_library(
            chunks, embeddings_index, set(document_ids)
        )

    bm25 = build_bm25_index(chunks)
    found = hybrid_search(bm25, embeddings_index, question, top_k=TOP_K)

    chunks_by_id = {c["chunk_id"]: c for c in chunks}
    top_chunks = [chunks_by_id[chunk_id] for chunk_id, _ in found]

    result = generate_answer(question, top_chunks)

    # Сохраняем запрос+ответ в историю
    log = QueryLog(question=question, answer=result["answer"])
    db.add(log)
    db.commit()
    db.refresh(log)

    return AskResponse(
        answer=result["answer"],
        sources=[Source(**s) for s in result["sources"]],
        query_log_id=log.id,
    )
