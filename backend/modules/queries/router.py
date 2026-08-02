"""The Question → Answer HTTP endpoint.

A thin layer: parse the input JSON into AskRequest, call service.ask,
return AskResponse. No logic lives here.
"""

from fastapi import APIRouter, Depends, HTTPException
from openai import OpenAIError
from sqlalchemy.orm import Session

from backend.core.database import get_session
from backend.core.errors import classify_pipeline_error
from backend.modules.queries import service
from backend.modules.queries.schemas import AskRequest, AskResponse, FlagRequest
from backend.modules.telemetry.service import track_report


router = APIRouter()


@router.post("/queries", response_model=AskResponse)
def create_query(
    payload: AskRequest,
    db: Session = Depends(get_session),
) -> AskResponse:
    """Ask a question → get an answer with source references."""
    try:
        return service.ask(
            question=payload.question,
            document_ids=payload.document_ids,
            db=db,
            mode=payload.mode,
            answer_model=payload.answer_model,
            expand=payload.expand,
            strong=payload.strong,
            answer_language=payload.answer_language,
        )
    except service.NoSearchableDocumentsError as exc:
        # Stale document selection — the user must refresh the filter.
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        # Empty library / incompatible embedding models — a readable
        # text from library_cache instead of HTTP 500.
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OpenAIError as exc:
        # OpenAI key / network / limits: the same classifier as
        # indexing — a readable message instead of a faceless HTTP 500.
        raise HTTPException(
            status_code=502, detail=classify_pipeline_error(exc)
        ) from exc


@router.post("/queries/flag")
def flag_query(payload: FlagRequest) -> dict:
    """Flag an answer as wrong/not-found → queue a report (F7).

    The sender forwards it to the license server. Queued rather than sent
    directly so it works offline and survives server downtime.
    """
    track_report(
        payload.question,
        payload.answer,
        payload.answer_model,
        payload.note,
        [c.model_dump() for c in payload.used_chunks],
    )
    return {"ok": True}
