"""Fail-open публичной сборки (решение 2026-07-15, PUBLIC_BUILD).

Пилотная сборка: офлайн дольше грейс-периода (1 день) блокирует UI,
отзыв — мгновенно. Публичная: недоступность сервера лицензий НИКОГДА
не блокирует работу; отзыв и принудительное обновление действуют как раньше.
"""

from datetime import timedelta

from backend.core.database import naive_utcnow
from backend.modules.auth import service
from backend.modules.auth.models import AuthSession


def _session(status: str, verified_days_ago: float) -> AuthSession:
    """Сессия без БД: compute_effective_status читает только поля."""
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
    # Ядро fail-open: даже год без связи с сервером — работаем.
    monkeypatch.setattr(service, "PUBLIC_BUILD", True)
    assert service.compute_effective_status(_session("offline", 365)) == "ok"


def test_public_revoked_still_blocks(monkeypatch):
    # Отзыв — явное решение владельца при живом сервере, fail-open его не отменяет.
    monkeypatch.setattr(service, "PUBLIC_BUILD", True)
    assert service.compute_effective_status(_session("revoked", 0)) == "blocked"


def test_public_update_required_still_blocks(monkeypatch):
    monkeypatch.setattr(service, "PUBLIC_BUILD", True)
    assert service.compute_effective_status(_session("update_required", 0)) == "blocked"
