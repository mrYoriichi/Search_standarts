"""AuthSession — local authorization state.

A single singleton row (id=1). No row — not logged in.
Fields:
  - token: JWT from the license server
  - username: the user's login (shown in the UI)
  - last_verified_at: time of the last successful server verify
  - last_verify_status: 'ok' | 'revoked' | 'offline'
        ok       — server answered 200, token valid
        revoked  — server answered 401/403, access revoked (instant block)
        offline  — server unreachable (network error / 5xx); the app works
                   while last_verified_at is younger than 1 day (grace
                   period; the public build never blocks on offline)
"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.database import Base


class AuthSession(Base):
    __tablename__ = "auth_session"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token: Mapped[str] = mapped_column(String)
    username: Mapped[str] = mapped_column(String)
    last_verified_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    last_verify_status: Mapped[str] = mapped_column(String, default="ok")
    # When the server sent 426, the URL lands here; the frontend shows it
    # in the "Install the new version" overlay. Otherwise NULL.
    download_url: Mapped[str | None] = mapped_column(String, nullable=True)
