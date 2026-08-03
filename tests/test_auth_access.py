"""Fail-open for the public build (decision 2026-07-15, PUBLIC_BUILD).

Pilot build: being offline longer than the grace period (1 day) blocks
the UI, revocation is immediate. Public build: license server downtime
NEVER blocks work; revocation and forced update still apply as before.
"""

from datetime import timedelta

from backend.core.database import naive_utcnow
from backend.modules.auth import service
from backend.modules.auth.models import AuthSession


def _session(status: str, verified_days_ago: float) -> AuthSession:
    """Session without a DB: compute_effective_status reads only the fields."""
    return AuthSession(
        id=1,
        token="t",
        username="u",
        last_verified_at=naive_utcnow() - timedelta(days=verified_days_ago),
        last_verify_status=status,
    )


def test_pilot_offline_beyond_grace_blocks(monkeypatch):
    monkeypatch.setattr(service, "PUBLIC_BUILD", False)
    assert service.compute_effective_status(_session("offline", 2)) == "blocked"


def test_pilot_offline_within_grace_ok(monkeypatch):
    monkeypatch.setattr(service, "PUBLIC_BUILD", False)
    assert service.compute_effective_status(_session("offline", 0.5)) == "ok"


def test_public_offline_never_blocks(monkeypatch):
    # The core of fail-open: even a year without server contact — keep working.
    monkeypatch.setattr(service, "PUBLIC_BUILD", True)
    assert service.compute_effective_status(_session("offline", 365)) == "ok"


def test_public_revoked_still_blocks(monkeypatch):
    # Revocation is an explicit owner decision made while the server is
    # alive; fail-open does not override it.
    monkeypatch.setattr(service, "PUBLIC_BUILD", True)
    assert service.compute_effective_status(_session("revoked", 0)) == "blocked"


def test_public_update_required_still_blocks(monkeypatch):
    monkeypatch.setattr(service, "PUBLIC_BUILD", True)
    assert service.compute_effective_status(_session("update_required", 0)) == "blocked"
