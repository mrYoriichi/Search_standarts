"""HTTP endpoints of the auth module.

POST /api/auth/login           — trade login/password for a JWT via the license server.
GET  /api/auth/status          — is there a local session and in what state.
POST /api/auth/logout          — delete the local session.
GET  /api/auth/profile         — current user profile (license-server proxy).
PUT  /api/auth/profile         — update the profile (proxy).
POST /api/auth/change-password — change the password (proxy).
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.core.database import get_session
from backend.core.ui_messages import msg
from backend.modules.auth import service
from backend.modules.auth.schemas import (
    ChangePasswordRequest,
    LoginRequest,
    LoginResponse,
    ProfileResponse,
    ProfileUpdate,
    RegisterRequest,
    StatusResponse,
)


router = APIRouter()


@router.post("/auth/login", response_model=LoginResponse)
def login(body: LoginRequest, db: Session = Depends(get_session)) -> LoginResponse:
    try:
        session = service.login(db, body.username, body.password)
    except service.UpdateRequiredError as exc:
        # 426 — the client is older than the server's MIN_SUPPORTED_VERSION.
        # The detail dict lets the frontend pull the download link.
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
        # 503 — the proper code for "a dependency is not answering".
        raise HTTPException(
            status_code=503,
            detail=msg("auth.server_unavailable"),
        ) from exc
    return LoginResponse(username=session.username)


@router.post("/auth/register", response_model=LoginResponse)
def register(
    body: RegisterRequest, db: Session = Depends(get_session)
) -> LoginResponse:
    try:
        session = service.register(db, body.model_dump())
    except service.UpdateRequiredError as exc:
        raise HTTPException(
            status_code=426,
            detail={
                "message": "Update required",
                "download_url": exc.download_url,
            },
        ) from exc
    except service.LoginError as exc:
        # 409 — name taken, 400 — short login/password (server text).
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    except service.LicenseServerUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail=msg("auth.server_unavailable"),
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
    """Translate profile-service errors into HTTPException. Shared wrapper."""
    if isinstance(exc, service.NotLoggedInError):
        raise HTTPException(status_code=401, detail="Not logged in") from exc
    if isinstance(exc, service.LicenseServerUnavailable):
        raise HTTPException(
            status_code=503,
            detail=msg("auth.server_unavailable"),
        ) from exc
    if isinstance(exc, service.ProfileError):
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    raise exc


@router.get("/auth/profile", response_model=ProfileResponse)
def get_profile(db: Session = Depends(get_session)) -> ProfileResponse:
    """Current user profile (license-server proxy)."""
    try:
        return ProfileResponse(**service.get_profile(db))
    except Exception as exc:  # noqa: BLE001 — typed in the wrapper
        _handle_profile_errors(exc)


@router.put("/auth/profile", response_model=ProfileResponse)
def update_profile(
    body: ProfileUpdate, db: Session = Depends(get_session)
) -> ProfileResponse:
    """Save the profile (license-server proxy)."""
    try:
        return ProfileResponse(**service.update_profile(db, body.model_dump()))
    except Exception as exc:  # noqa: BLE001
        _handle_profile_errors(exc)


@router.post("/auth/change-password")
def change_password(
    body: ChangePasswordRequest, db: Session = Depends(get_session)
) -> dict:
    """Change the password (license-server proxy)."""
    try:
        service.change_password(db, body.old_password, body.new_password)
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001
        _handle_profile_errors(exc)
