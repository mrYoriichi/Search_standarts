"""Protecting stored secrets at rest (the OpenAI key and the login token).

The key is money, and app.db travels: backups, a roamed Windows profile, a
lost laptop. Windows DPAPI ties the stored value to the user's account, so
a copied file is useless elsewhere. Nothing here protects against code
running as that user — it can simply ask Windows to decrypt.

The Windows call itself cannot run on the development Mac, so these tests
fake the platform layer and pin the behaviour around it: what gets stored,
what happens to old plaintext values, and that an unreadable value never
crashes the app.
"""

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.core import secrets
from backend.core.database import Base
from backend.modules.auth import service as auth_service
from backend.modules.auth.models import AuthSession
from backend.modules.settings import service
from backend.modules.settings.models import Setting


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture
def fake_dpapi(monkeypatch):
    """A reversible stand-in for the Windows call, available everywhere."""
    monkeypatch.setattr(secrets, "_available", lambda: True)
    monkeypatch.setattr(
        secrets, "_dpapi", lambda data, encrypt: data[::-1] if encrypt else data[::-1]
    )


def _stored(db) -> str:
    setting = db.scalar(select(Setting).where(Setting.key == service.OPENAI_KEY_KEY))
    return setting.value


def test_round_trip(fake_dpapi):
    protected = secrets.protect("sk-tajny-klic")
    assert protected != "sk-tajny-klic"
    assert secrets.unprotect(protected) == "sk-tajny-klic"


def test_plain_value_passes_through():
    """A key stored before this feature must stay readable."""
    assert secrets.unprotect("sk-legacy") == "sk-legacy"


def test_unreadable_value_returns_none(fake_dpapi, monkeypatch):
    """Restored to another account: better "set the key again" than a crash."""

    def boom(data: bytes, encrypt: bool) -> bytes:
        raise OSError("wrong user")

    monkeypatch.setattr(secrets, "_dpapi", boom)
    assert secrets.unprotect(secrets.PREFIX + "bm9uc2Vuc2U=") is None


def test_protect_falls_back_to_plain_when_it_fails(monkeypatch):
    """Losing the key would be worse than storing it as it is."""
    monkeypatch.setattr(secrets, "_available", lambda: True)
    monkeypatch.setattr(
        secrets, "_dpapi", lambda data, encrypt: (_ for _ in ()).throw(OSError("no"))
    )
    assert secrets.protect("sk-abc") == "sk-abc"


def test_key_is_not_stored_as_typed(db, fake_dpapi):
    service.set_openai_key(db, "sk-tajny-klic")

    assert _stored(db) != "sk-tajny-klic"
    assert service.get_openai_key(db) == "sk-tajny-klic"


def test_legacy_plain_key_is_upgraded_on_start(db, fake_dpapi):
    db.add(Setting(key=service.OPENAI_KEY_KEY, value="sk-legacy"))
    db.commit()

    service.apply_openai_key_to_env(db)

    assert _stored(db) != "sk-legacy"  # rewritten protected
    assert service.get_openai_key(db) == "sk-legacy"


def test_login_token_is_not_stored_as_typed(db, fake_dpapi):
    auth_service._persist_session(db, "anna", "jwt-abc")

    assert db.get(AuthSession, 1).token != "jwt-abc"
    assert auth_service.session_token(db.get(AuthSession, 1)) == "jwt-abc"


def test_unreadable_token_counts_as_logged_out(db, fake_dpapi, monkeypatch):
    """A DB restored under another account: show the login screen.

    Better than an account that looks signed in but cannot talk to the
    license server at all.
    """
    auth_service._persist_session(db, "anna", "jwt-abc")

    def boom(data: bytes, encrypt: bool) -> bytes:
        raise OSError("wrong user")

    monkeypatch.setattr(secrets, "_dpapi", boom)

    assert auth_service.get_session(db) is None


def test_legacy_plain_token_is_upgraded_on_verify(fake_dpapi, monkeypatch):
    """Users already logged in must not stay unprotected until a re-login."""
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(auth_service, "SessionLocal", factory)
    monkeypatch.setattr(
        auth_service,
        "verify_with_server",
        lambda token: auth_service.VerifyResult("ok"),
    )
    setup = factory()
    setup.add(AuthSession(id=1, token="jwt-legacy", username="anna"))
    setup.commit()
    setup.close()

    auth_service.verify_once()

    check = factory()
    session = check.get(AuthSession, 1)
    assert session.token != "jwt-legacy"  # rewritten protected
    assert auth_service.session_token(session) == "jwt-legacy"
    check.close()


def test_unreadable_key_does_not_break_startup(db, fake_dpapi, monkeypatch):
    db.add(Setting(key=service.OPENAI_KEY_KEY, value=secrets.PREFIX + "bm9uc2Vuc2U="))
    db.commit()

    def boom(data: bytes, encrypt: bool) -> bytes:
        raise OSError("wrong user")

    monkeypatch.setattr(secrets, "_dpapi", boom)

    service.apply_openai_key_to_env(db)  # must not raise

    assert service.get_openai_key(db) is None
