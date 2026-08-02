"""FastAPI dependency guarding endpoints.

Attached to routers that require login. /api/auth/* and /api/health go
without it.
"""

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.core.database import get_session
from backend.modules.auth import service
from backend.modules.auth.models import AuthSession


def require_auth(db: Session = Depends(get_session)) -> AuthSession:
    """401 when there is no local session or the session is 'blocked'."""
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
