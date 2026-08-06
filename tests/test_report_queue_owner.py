"""A queued report must reach the server as its own author.

Audit 2026-08-06 #6: PendingReport stored no owner, and the Bearer token
was attached at SEND time from the current session. If sending failed and
another user logged in on the same installation, the first user's question
and document fragments went out under the second user's name.

Anonymous PendingEvent rows keep the old behaviour on purpose: they carry
no personal data, only usage counters.
"""

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.core.database import Base
from backend.modules.auth.models import AuthSession
from backend.modules.telemetry import service
from backend.modules.telemetry.models import PendingReport


@pytest.fixture
def session_factory(monkeypatch):
    """One shared in-memory DB for every session the service opens."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(service, "SessionLocal", factory)
    return factory


@pytest.fixture
def sent(monkeypatch):
    """Capture batches instead of posting them to the license server."""
    calls: list[tuple[str, dict, str]] = []

    def fake_post(endpoint: str, body: dict, token: str) -> bool:
        calls.append((endpoint, body, token))
        return True

    monkeypatch.setattr(service, "_post_batch", fake_post)
    return calls


def _login(factory, username: str) -> None:
    """Log this installation in as `username` (the singleton is overwritten)."""
    db = factory()
    session = db.get(AuthSession, 1)
    if session is None:
        db.add(AuthSession(id=1, token=f"token-{username}", username=username))
    else:
        session.token = f"token-{username}"
        session.username = username
    db.commit()
    db.close()


def _queued(factory) -> list[PendingReport]:
    db = factory()
    try:
        return list(db.scalars(select(PendingReport)).all())
    finally:
        db.close()


def test_report_waits_for_its_own_author(session_factory, sent):
    _login(session_factory, "anna")
    service.track_report(question="proc?", answer="protoze")

    _login(session_factory, "bob")
    assert service.send_pending_report_batch() == 0
    assert sent == []
    assert len(_queued(session_factory)) == 1  # kept, not dropped

    _login(session_factory, "anna")
    assert service.send_pending_report_batch() == 1
    assert sent[0][2] == "token-anna"
    assert _queued(session_factory) == []


def test_report_of_the_current_user_is_sent(session_factory, sent):
    _login(session_factory, "anna")
    service.track_report(question="proc?", answer="protoze", note="spatne")

    assert service.send_pending_report_batch() == 1
    endpoint, body, token = sent[0]
    assert endpoint == "/telemetry/flagged"
    assert body["events"][0]["note"] == "spatne"
    assert token == "token-anna"


def test_row_without_owner_is_still_sent(session_factory, sent):
    """Rows queued before the upgrade have no owner — do not strand them."""
    db = session_factory()
    db.add(PendingReport(question="proc?", answer="protoze"))
    db.commit()
    db.close()

    _login(session_factory, "bob")

    assert service.send_pending_report_batch() == 1
