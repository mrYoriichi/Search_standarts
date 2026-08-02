"""Authorization service: talk to the license server, keep the token
in the local DB.

`AuthSession` is a singleton (id=1). No row — not logged in.
"""

import asyncio
import os
from dataclasses import dataclass
from datetime import timedelta

import httpx
from sqlalchemy.orm import Session

from backend.core.database import SessionLocal, naive_utcnow
from backend.core.ui_messages import msg
from backend.modules.auth.models import AuthSession
from backend.version import APP_VERSION, PUBLIC_BUILD


# Header for every license-server request. The server compares it with
# MIN_SUPPORTED_VERSION and answers 426 Upgrade Required when outdated.
VERSION_HEADERS = {"X-App-Version": APP_VERSION}

# Defaults to the production server; local tests may override it in
# .env: LICENSE_SERVER_URL=http://127.0.0.1:8001
LICENSE_SERVER_URL = os.getenv(
    "LICENSE_SERVER_URL", "https://license-server-jc68.onrender.com"
)

# License-server request timeout. Render Starter can cold-start for
# ~10 s, plus network margin.
HTTP_TIMEOUT = 15.0

# The license server is pinged hourly.
VERIFY_INTERVAL_SECONDS = 60 * 60

# How long the app works without reaching the license server (pilot
# build). Shorter — nagging on a bad network; longer — too slow after a
# revocation.
GRACE_PERIOD = timedelta(days=1)


class LoginError(Exception):
    """The server answered but login failed (bad credentials / revoked)."""

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(message)


class LicenseServerUnavailable(Exception):
    """Server unreachable (network error / 5xx). The user sees "try later"."""


class UpdateRequiredError(Exception):
    """Server answered 426: the client is older than MIN_SUPPORTED_VERSION."""

    def __init__(self, download_url: str):
        self.download_url = download_url
        super().__init__("Update required")


@dataclass
class VerifyResult:
    """Result of the token check on the license server."""

    status: str  # 'ok' | 'revoked' | 'offline' | 'update_required'
    download_url: str | None = None


def login(db: Session, username: str, password: str) -> AuthSession:
    """Get a JWT from the license server and store it as the singleton.

    An existing row (returning user) is overwritten.
    """
    try:
        response = httpx.post(
            f"{LICENSE_SERVER_URL}/auth/login",
            json={"username": username, "password": password},
            headers=VERSION_HEADERS,
            timeout=HTTP_TIMEOUT,
        )
    except httpx.HTTPError as exc:
        raise LicenseServerUnavailable(str(exc)) from exc

    if response.status_code == 426:
        # Client older than MIN_SUPPORTED_VERSION — no entry until updated.
        detail = response.json().get("detail", {})
        raise UpdateRequiredError(detail.get("download_url", ""))

    if response.status_code >= 500:
        raise LicenseServerUnavailable(
            f"License server returned {response.status_code}"
        )

    if response.status_code != 200:
        # 401 — bad credentials, 403 — revoked. The server distinguishes.
        detail = response.json().get("detail", "Login failed")
        raise LoginError(response.status_code, detail)

    return _persist_session(db, username, response.json()["token"])


def register(db: Session, fields: dict) -> AuthSession:
    """Create an account on the license server and log in right away.

    `fields` is the registration body (email, password, full_name,
    company, position, linkedin). The server returns the same response as
    login (token+username), so success is indistinguishable from a
    regular sign-in.
    """
    try:
        response = httpx.post(
            f"{LICENSE_SERVER_URL}/auth/register",
            json=fields,
            headers=VERSION_HEADERS,
            timeout=HTTP_TIMEOUT,
        )
    except httpx.HTTPError as exc:
        raise LicenseServerUnavailable(str(exc)) from exc

    if response.status_code == 426:
        detail = response.json().get("detail", {})
        raise UpdateRequiredError(detail.get("download_url", ""))

    if response.status_code >= 500:
        raise LicenseServerUnavailable(
            f"License server returned {response.status_code}"
        )

    if response.status_code != 200:
        # 409 — email taken, 400 — invalid/incomplete data. Text passed on.
        detail = response.json().get("detail", "Registration failed")
        raise LoginError(response.status_code, detail)

    data = response.json()  # {token, username} — username == email
    return _persist_session(db, data["username"], data["token"])


def _persist_session(db: Session, username: str, token: str) -> AuthSession:
    """Store the JWT in the AuthSession singleton (id=1); shared by
    login/register. An existing row is overwritten.
    """
    session = db.get(AuthSession, 1)
    if session is None:
        session = AuthSession(
            id=1,
            token=token,
            username=username,
            last_verified_at=naive_utcnow(),
            last_verify_status="ok",
            download_url=None,
        )
        db.add(session)
    else:
        session.token = token
        session.username = username
        session.last_verified_at = naive_utcnow()
        session.last_verify_status = "ok"
        session.download_url = None
    db.commit()
    db.refresh(session)
    return session


def get_session(db: Session) -> AuthSession | None:
    return db.get(AuthSession, 1)


class NotLoggedInError(Exception):
    """No local session — nothing to proxy to the license server."""


class ProfileError(Exception):
    """The license server answered a profile/password request with an error.

    status_code and message are passed through so the frontend can show
    the text (e.g. "wrong current password").
    """

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(message)


def _auth_headers(token: str) -> dict[str, str]:
    """Bearer token + client version — the shared profile-request headers."""
    return {"Authorization": f"Bearer {token}", **VERSION_HEADERS}


def get_profile(db: Session) -> dict:
    """Fetch the current user profile from the license server (GET /auth/me)."""
    session = get_session(db)
    if session is None:
        raise NotLoggedInError()
    try:
        response = httpx.get(
            f"{LICENSE_SERVER_URL}/auth/me",
            headers=_auth_headers(session.token),
            timeout=HTTP_TIMEOUT,
        )
    except httpx.HTTPError as exc:
        raise LicenseServerUnavailable(str(exc)) from exc

    if response.status_code != 200:
        raise ProfileError(response.status_code, msg("profile.load_failed"))
    return response.json()


def update_profile(db: Session, fields: dict) -> dict:
    """Update the profile on the license server (PUT /auth/me)."""
    session = get_session(db)
    if session is None:
        raise NotLoggedInError()
    try:
        response = httpx.put(
            f"{LICENSE_SERVER_URL}/auth/me",
            json=fields,
            headers=_auth_headers(session.token),
            timeout=HTTP_TIMEOUT,
        )
    except httpx.HTTPError as exc:
        raise LicenseServerUnavailable(str(exc)) from exc

    if response.status_code != 200:
        raise ProfileError(response.status_code, msg("profile.save_failed"))
    return response.json()


def change_password(db: Session, old_password: str, new_password: str) -> None:
    """Change the password on the license server (POST /auth/change-password)."""
    session = get_session(db)
    if session is None:
        raise NotLoggedInError()
    try:
        response = httpx.post(
            f"{LICENSE_SERVER_URL}/auth/change-password",
            json={"old_password": old_password, "new_password": new_password},
            headers=_auth_headers(session.token),
            timeout=HTTP_TIMEOUT,
        )
    except httpx.HTTPError as exc:
        raise LicenseServerUnavailable(str(exc)) from exc

    if response.status_code == 400:
        # Server text ("wrong old password" / "too short") passes through.
        detail = response.json().get("detail", msg("profile.password_change_failed"))
        raise ProfileError(400, detail)
    if response.status_code != 200:
        raise ProfileError(response.status_code, msg("profile.password_change_failed"))


def logout(db: Session) -> None:
    """Delete the singleton row — the next UI start shows the login screen."""
    session = db.get(AuthSession, 1)
    if session is not None:
        db.delete(session)
        db.commit()


def verify_with_server(token: str) -> VerifyResult:
    """Call /auth/verify on the license server; returns a status tag.

    - 'ok'              — 200, token valid.
    - 'revoked'         — 401/403: broken/expired token or user revoked.
    - 'update_required' — 426: client older than MIN_SUPPORTED_VERSION;
                          the server sends download_url.
    - 'offline'         — server unreachable (network error / 5xx); also
                          hit with no network — this is the grace period.
    """
    headers = {"Authorization": f"Bearer {token}", **VERSION_HEADERS}
    try:
        response = httpx.get(
            f"{LICENSE_SERVER_URL}/auth/verify",
            headers=headers,
            timeout=HTTP_TIMEOUT,
        )
    except httpx.HTTPError:
        return VerifyResult(status="offline")

    if response.status_code == 200:
        return VerifyResult(status="ok")
    if response.status_code in (401, 403):
        return VerifyResult(status="revoked")
    if response.status_code == 426:
        detail = response.json().get("detail", {})
        return VerifyResult(
            status="update_required",
            download_url=detail.get("download_url", ""),
        )
    return VerifyResult(status="offline")  # 5xx and the rest — unreachable


def verify_once() -> None:
    """One verify iteration: updates the session status in the DB.

    Opens its own SQLAlchemy session — this runs outside FastAPI
    dependencies (a background loop).
    """
    db = SessionLocal()
    try:
        session = db.get(AuthSession, 1)
        if session is None:
            return  # not logged in — nothing to verify
        result = verify_with_server(session.token)
        if result.status == "ok":
            session.last_verified_at = naive_utcnow()
            session.download_url = None
        else:
            # On offline/revoked/update_required last_verified_at is NOT
            # updated — the grace-period clock ticks from the last
            # successful verify.
            session.download_url = result.download_url
        session.last_verify_status = result.status
        db.commit()
    finally:
        db.close()


async def run_verify_loop() -> None:
    """Background coroutine: verify the token hourly, starting immediately."""
    while True:
        try:
            # httpx is sync — keep the event loop unblocked.
            await asyncio.to_thread(verify_once)
        except Exception as exc:  # pylint: disable=broad-except
            # Log and continue — the loop outlives any single error.
            print(f"[verify_loop] error: {exc}")
        await asyncio.sleep(VERIFY_INTERVAL_SECONDS)


def compute_effective_status(session: AuthSession) -> str:
    """Fold last_verify_status and the age of last_verified_at into one
    decision: 'ok' or 'blocked' (the UI locks on 'blocked').

    - revoked / update_required → blocked instantly (the server said an
      explicit no — the owner's deliberate action, both builds).
    - offline → pilot build: blocked when the last successful verify is
      >1 day old; public build (PUBLIC_BUILD, fail-open): offline NEVER
      blocks — an unreachable license server must not stop the work.
    - ok      → ok.
    """
    if session.last_verify_status in ("revoked", "update_required"):
        return "blocked"
    if session.last_verify_status == "offline" and not PUBLIC_BUILD:
        age = naive_utcnow() - session.last_verified_at
        if age > GRACE_PERIOD:
            return "blocked"
    return "ok"
