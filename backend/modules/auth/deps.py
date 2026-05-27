"""FastAPI-зависимость для защиты эндпоинтов.

Прицепляем к роутерам, требующим логина. /api/auth/* и /api/health — без неё.
"""

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.core.database import get_session
from backend.modules.auth import service
from backend.modules.auth.models import AuthSession


def require_auth(db: Session = Depends(get_session)) -> AuthSession:
    """401, если нет локальной сессии или сессия в состоянии 'blocked'."""
    session = service.get_session(db)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not logged in",
        )
    if service.compute_effective_status(session) == "blocked":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Access revoked or grace period expired",
        )
    return session
