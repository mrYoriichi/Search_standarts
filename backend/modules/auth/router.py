"""HTTP-эндпоинты модуля auth.

POST /api/auth/login  — обмен логина/пароля на JWT через сервер лицензий.
GET  /api/auth/status — есть ли локальная сессия и в каком она статусе.
POST /api/auth/logout — удаляет локальную сессию.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.core.database import get_session
from backend.modules.auth import service
from backend.modules.auth.schemas import (
    LoginRequest,
    LoginResponse,
    StatusResponse,
)


router = APIRouter()


@router.post("/auth/login", response_model=LoginResponse)
def login(
    body: LoginRequest, db: Session = Depends(get_session)
) -> LoginResponse:
    try:
        session = service.login(db, body.username, body.password)
    except service.UpdateRequiredError as exc:
        # 426 — версия клиента младше MIN_SUPPORTED_VERSION на сервере лицензий.
        # detail-dict позволяет фронту достать ссылку на скачивание.
        raise HTTPException(
            status_code=426,
            detail={
                "message": "Update required",
                "download_url": exc.download_url,
            },
        ) from exc
    except service.LoginError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    except service.LicenseServerUnavailable as exc:
        # 503 — корректный код для «зависимый сервис не отвечает».
        raise HTTPException(
            status_code=503,
            detail="Сервер лицензий недоступен. Попробуйте позже.",
        ) from exc
    return LoginResponse(username=session.username)


@router.get("/auth/status", response_model=StatusResponse)
def status(db: Session = Depends(get_session)) -> StatusResponse:
    session = service.get_session(db)
    if session is None:
        return StatusResponse(logged_in=False)
    return StatusResponse(
        logged_in=True,
        username=session.username,
        status=session.last_verify_status,
        effective_status=service.compute_effective_status(session),
        last_verified_at=session.last_verified_at,
        download_url=session.download_url,
    )


@router.post("/auth/logout")
def logout(db: Session = Depends(get_session)) -> dict:
    service.logout(db)
    return {"ok": True}
