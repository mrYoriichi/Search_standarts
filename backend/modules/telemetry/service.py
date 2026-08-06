"""Telemetry service: queue events locally, a background coroutine sends them.

Public API:
- `track_event(name, **props)` — enqueue an event. Cheap and safe.
- `run_telemetry_sender()` — background loop, started in the lifespan.

Principles:
- Not logged in — nothing is sent; events accumulate.
- Server unreachable — nothing is deleted; retried next tick.
- Server returned 200 — exactly the sent rows are deleted by id.
- A sending failure must never take down the app (try/except all around).
"""

import asyncio
from typing import Any

import httpx
from sqlalchemy import select

from backend.core.database import SessionLocal
from backend.modules.auth.models import AuthSession
from backend.modules.auth.service import (
    HTTP_TIMEOUT,
    LICENSE_SERVER_URL,
    VERSION_HEADERS,
    session_token,
)
from backend.modules.telemetry.models import PendingEvent, PendingReport


# Send once a minute. More often — needless traffic; less — staler reports.
SEND_INTERVAL_SECONDS = 60

# Batch cap; generous — events rarely pile up.
BATCH_LIMIT = 100


def track_event(name: str, **props: Any) -> None:
    """Put an event into the local queue.

    Any failure (DB, disk) is swallowed: telemetry must NOT crash the app.
    """
    try:
        db = SessionLocal()
        try:
            db.add(PendingEvent(name=name, props=props or None))
            db.commit()
        finally:
            db.close()
    except Exception as exc:  # pylint: disable=broad-except
        print(f"[telemetry] track_event({name}) failed: {exc}")


def track_report(
    question: str,
    answer: str,
    answer_model: str | None = None,
    note: str | None = None,
    chunks: list[dict] | None = None,
) -> None:
    """Queue a flagged answer ("Report", F7).

    Triggered by an explicit user action (the button under the answer),
    so no consent check — the click is the consent. chunks — the used
    fragments with text. Errors are swallowed like in track_event.
    """
    try:
        db = SessionLocal()
        try:
            session = db.get(AuthSession, 1)
            db.add(
                PendingReport(
                    username=session.username if session else None,
                    question=question,
                    answer=answer,
                    answer_model=answer_model,
                    note=note,
                    chunks=chunks or None,
                )
            )
            db.commit()
        finally:
            db.close()
    except Exception as exc:  # pylint: disable=broad-except
        print(f"[telemetry] track_report failed: {exc}")


def _post_batch(endpoint: str, body: dict, token: str) -> bool:
    """POST a batch to the license server. True — accepted (200), queue clears.

    Non-200 / network error returns False: the batch stays queued until
    the next tick. 401 (token), 426 (outdated), 5xx — same strategy.
    """
    headers = {"Authorization": f"Bearer {token}", **VERSION_HEADERS}
    try:
        response = httpx.post(
            f"{LICENSE_SERVER_URL}{endpoint}",
            json=body,
            headers=headers,
            timeout=HTTP_TIMEOUT,
        )
    except httpx.HTTPError as exc:
        print(f"[telemetry] network error on {endpoint}: {exc}")
        return False
    if response.status_code != 200:
        print(f"[telemetry] {endpoint} returned {response.status_code}, keeping batch")
        return False
    return True


def send_pending_batch() -> int:
    """Send one batch of anonymous events. Returns how many were sent.

    Not logged in — 0. Non-200 from the server — events stay queued.
    """
    db = SessionLocal()
    try:
        session = db.get(AuthSession, 1)
        token = session_token(session) if session else None
        if token is None:
            return 0  # nobody to send as — not logged in (or token unreadable)

        rows = db.scalars(
            select(PendingEvent).order_by(PendingEvent.id).limit(BATCH_LIMIT)
        ).all()
        if not rows:
            return 0

        body = {
            "events": [
                {
                    "name": row.name,
                    "props": row.props or {},
                    "client_timestamp": row.client_timestamp.isoformat(),
                }
                for row in rows
            ]
        }
        if not _post_batch("/telemetry/events", body, token):
            return 0

        ids = [row.id for row in rows]
        db.query(PendingEvent).filter(PendingEvent.id.in_(ids)).delete(
            synchronize_session=False
        )
        db.commit()
        return len(ids)
    finally:
        db.close()


def send_pending_report_batch() -> int:
    """Send one batch of flagged answers (F7). Returns how many were sent.

    Same behaviour as send_pending_batch, but the /telemetry/flagged
    endpoint and the q/a text.
    """
    db = SessionLocal()
    try:
        session = db.get(AuthSession, 1)
        token = session_token(session) if session else None
        if token is None:
            return 0

        # Only this user's reports: the token is attached here, so someone
        # else's queued report would be filed under the current account.
        # A foreign row waits for its author to log back in; a row with no
        # author (queued before the column existed) goes out as before.
        rows = db.scalars(
            select(PendingReport)
            .where(
                (PendingReport.username == session.username)
                | (PendingReport.username.is_(None))
            )
            .order_by(PendingReport.id)
            .limit(BATCH_LIMIT)
        ).all()
        if not rows:
            return 0

        body = {
            "events": [
                {
                    "question": row.question,
                    "answer": row.answer,
                    "answer_model": row.answer_model,
                    "note": row.note,
                    "chunks": row.chunks or [],
                    "client_timestamp": row.client_timestamp.isoformat(),
                }
                for row in rows
            ]
        }
        if not _post_batch("/telemetry/flagged", body, token):
            return 0

        ids = [row.id for row in rows]
        db.query(PendingReport).filter(PendingReport.id.in_(ids)).delete(
            synchronize_session=False
        )
        db.commit()
        return len(ids)
    finally:
        db.close()


async def run_telemetry_sender() -> None:
    """Background coroutine: send events and flagged answers once a minute."""
    while True:
        try:
            await asyncio.to_thread(send_pending_batch)
            await asyncio.to_thread(send_pending_report_batch)
        except Exception as exc:  # pylint: disable=broad-except
            print(f"[telemetry] sender error: {exc}")
        await asyncio.sleep(SEND_INTERVAL_SECONDS)
