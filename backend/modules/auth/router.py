"""HTTP-эндпоинты модуля auth.

POST /api/auth/login           — обмен логина/пароля на JWT через сервер лицензий.
GET  /api/auth/status          — есть ли локальная сессия и в каком она статусе.
POST /api/auth/logout          — удаляет локальную сессию.
GET  /api/auth/profile         — профиль текущего юзера (прокси на сервер лицензий).
PUT  /api/auth/profile         — обновить профиль (прокси).
POST /api/auth/change-password — сменить пароль (прокси).
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.core.database import get_session
from backend.modules.auth import service
from backend.modules.auth.schemas import (
    ChangePasswordRequest,
    LoginRequest,
    LoginResponse,
    ProfileResponse,
    ProfileUpdate,
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


def _handle_profile_errors(exc: Exception) -> None:
    """Переводит ошибки сервиса профиля в HTTPException. Общая обёртка."""
    if isinstance(exc, service.NotLoggedInError):
        raise HTTPException(status_code=401, detail="Not logged in") from exc
    if isinstance(exc, service.LicenseServerUnavailable):
        raise HTTPException(
            status_code=503,
            detail="Licenční server není dostupný. Zkuste to později.",
        ) from exc
    if isinstance(exc, service.ProfileError):
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    raise exc


@router.get("/auth/profile", response_model=ProfileResponse)
def get_profile(db: Session = Depends(get_session)) -> ProfileResponse:
    """Профиль текущего юзера (проксируем на сервер лицензий)."""
    try:
        return ProfileResponse(**service.get_profile(db))
    except Exception as exc:  # noqa: BLE001 — раскладываем по типам в обёртке
        _handle_profile_errors(exc)


@router.put("/auth/profile", response_model=ProfileResponse)
def update_profile(
    body: ProfileUpdate, db: Session = Depends(get_session)
) -> ProfileResponse:
    """Сохраняет профиль (проксируем на сервер лицензий)."""
    try:
        return ProfileResponse(**service.update_profile(db, body.model_dump()))
    except Exception as exc:  # noqa: BLE001
        _handle_profile_errors(exc)


@router.post("/auth/change-password")
def change_password(
    body: ChangePasswordRequest, db: Session = Depends(get_session)
) -> dict:
    """Смена пароля (проксируем на сервер лицензий)."""
    try:
        service.change_password(db, body.old_password, body.new_password)
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001
        _handle_profile_errors(exc)
