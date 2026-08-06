"""PendingEvent — the local telemetry queue before sending.

Events land here via `track_event()`. The background coroutine
`run_telemetry_sender` takes a batch, sends it to the license server and
deletes on success.

When the server is unreachable or the user is not logged in, events
accumulate — nothing is lost.
"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.database import Base


class PendingEvent(Base):
    __tablename__ = "pending_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String)
    # SQLAlchemy serializes dict ↔ JSON automatically (TEXT in SQLite).
    props: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Client-side event time (when it actually happened).
    client_timestamp: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )


class PendingReport(Base):
    """Queue of "Report" complaints (F7): answers the user flagged as bad.

    Separate from PendingEvent — this is personal data, stored ONLY when
    the user explicitly clicked "Report" on an answer. The sender posts
    to /telemetry/flagged and deletes on success. note — the user's
    optional remark ("why it is wrong").
    """

    __tablename__ = "pending_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Who clicked "Report". The token is attached at send time, so without
    # this an unsent report would go out under whoever logs in next.
    # NULL — a row queued before this column existed.
    username: Mapped[str | None] = mapped_column(String, nullable=True)
    question: Mapped[str] = mapped_column(String)
    answer: Mapped[str] = mapped_column(String)
    answer_model: Mapped[str | None] = mapped_column(String, nullable=True)
    note: Mapped[str | None] = mapped_column(String, nullable=True)
    # The used fragments (with text) — list[dict]; SQLAlchemy ↔ JSON.
    chunks: Mapped[list | None] = mapped_column(JSON, nullable=True)
    client_timestamp: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
