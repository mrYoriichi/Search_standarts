"""HTTP-эндпоинт «Вопрос → Ответ».

Тонкая прокладка: парсит входной JSON в AskRequest, дергает service.ask,
возвращает AskResponse. Никакой логики здесь нет.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.core.database import get_session
from backend.modules.queries import service
from backend.modules.queries.schemas import AskRequest, AskResponse, FlagRequest
from backend.modules.telemetry.service import track_report


router = APIRouter()


@router.post("/queries", response_model=AskResponse)
def create_query(
    payload: AskRequest,
    db: Session = Depends(get_session),
) -> AskResponse:
    """Задать вопрос → получить ответ со ссылками на источники."""
    return service.ask(
        question=payload.question,
        document_ids=payload.document_ids,
        db=db,
        mode=payload.mode,
        answer_model=payload.answer_model,
    )


@router.post("/queries/flag")
def flag_query(payload: FlagRequest) -> dict:
    """Пометить ответ как неверный/ненайденный → положить отчёт в очередь (F7).

    Sender отправит владельцу на сервер лицензий. Кладём в очередь, а не шлём
    сразу, — чтобы работало офлайн и переживало недоступность сервера.
    """
    track_report(
        payload.question,
        payload.answer,
        payload.answer_model,
        payload.note,
        [c.model_dump() for c in payload.used_chunks],
    )
    return {"ok": True}
