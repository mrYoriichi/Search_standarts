"""Сервис авторизации: ходим на сервер лицензий, кладём токен в локальную БД.

`AuthSession` — синглтон (id=1). Если строки нет, юзер не залогинен.
"""

import asyncio
import os
from dataclasses import dataclass
from datetime import datetime, timedelta

import httpx
from sqlalchemy.orm import Session

from backend.core.database import SessionLocal
from backend.modules.auth.models import AuthSession
from backend.version import APP_VERSION


# Хедер для всех запросов к серверу лицензий. Сервер сверяет с MIN_SUPPORTED_VERSION
# и при устаревшей версии отвечает 426 Upgrade Required (см. блок F5).
VERSION_HEADERS = {"X-App-Version": APP_VERSION}

# Дефолт указывает на прод-сервер. Для локальных тестов можно
# переопределить в .env: LICENSE_SERVER_URL=http://127.0.0.1:8001
LICENSE_SERVER_URL = os.getenv(
    "LICENSE_SERVER_URL", "https://license-server-jc68.onrender.com"
)

# Таймаут на запрос к серверу лицензий. Render Starter может «холодно стартовать»
# до ~10 сек, плюс запас на сеть.
HTTP_TIMEOUT = 15.0

# Каждый час дёргаем сервер лицензий. См. F4.3 в PROJECT_STATE.md.
VERIFY_INTERVAL_SECONDS = 60 * 60

# Сколько дней мы готовы работать без связи с сервером лицензий.
# Меньше — назойливо для юзера в плохой сети. Больше — слишком долго после отзыва.
GRACE_PERIOD = timedelta(days=1)


class LoginError(Exception):
    """Сервер ответил, но логин не прошёл (неверные данные / отозван)."""

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(message)


class LicenseServerUnavailable(Exception):
    """Сервер недоступен (network error / 5xx). Юзеру говорим «попробуйте позже»."""


class UpdateRequiredError(Exception):
    """Сервер ответил 426: версия клиента младше MIN_SUPPORTED_VERSION."""

    def __init__(self, download_url: str):
        self.download_url = download_url
        super().__init__("Update required")


@dataclass
class VerifyResult:
    """Результат проверки токена на сервере лицензий."""

    status: str  # 'ok' | 'revoked' | 'offline' | 'update_required'
    download_url: str | None = None


def login(db: Session, username: str, password: str) -> AuthSession:
    """Ходит на сервер лицензий, получает JWT, сохраняет в БД синглтоном.

    Если строка уже есть (старый юзер) — перезаписываем.
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
        # Версия клиента младше MIN_SUPPORTED_VERSION. До обновления — не пустим.
        detail = response.json().get("detail", {})
        raise UpdateRequiredError(detail.get("download_url", ""))

    if response.status_code >= 500:
        raise LicenseServerUnavailable(f"License server returned {response.status_code}")

    if response.status_code != 200:
        # 401 — неверные данные, 403 — отозван. Сервер сам разделяет.
        detail = response.json().get("detail", "Login failed")
        raise LoginError(response.status_code, detail)

    token = response.json()["token"]

    session = db.get(AuthSession, 1)
    if session is None:
        session = AuthSession(
            id=1,
            token=token,
            username=username,
            last_verified_at=datetime.utcnow(),
            last_verify_status="ok",
            download_url=None,
        )
        db.add(session)
    else:
        session.token = token
        session.username = username
        session.last_verified_at = datetime.utcnow()
        session.last_verify_status = "ok"
        session.download_url = None
    db.commit()
    db.refresh(session)
    return session


def get_session(db: Session) -> AuthSession | None:
    return db.get(AuthSession, 1)


class NotLoggedInError(Exception):
    """Нет локальной сессии — нечего проксировать на сервер лицензий."""


class ProfileError(Exception):
    """Сервер лицензий ответил ошибкой на профиль/смену пароля.

    status_code и message пробрасываем наружу, чтобы фронт показал текст
    (например «неверный текущий пароль»).
    """

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(message)


def _auth_headers(token: str) -> dict[str, str]:
    """Bearer-токен + версия клиента — общий набор для запросов профиля."""
    return {"Authorization": f"Bearer {token}", **VERSION_HEADERS}


def get_profile(db: Session) -> dict:
    """Тянет профиль текущего юзера с сервера лицензий (GET /auth/me)."""
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
        raise ProfileError(response.status_code, "Nepodařilo se načíst profil.")
    return response.json()


def update_profile(db: Session, fields: dict) -> dict:
    """Обновляет профиль на сервере лицензий (PUT /auth/me)."""
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
        raise ProfileError(response.status_code, "Nepodařilo se uložit profil.")
    return response.json()


def change_password(db: Session, old_password: str, new_password: str) -> None:
    """Меняет пароль на сервере лицензий (POST /auth/change-password)."""
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
        # Серверный текст («неверный старый пароль» / «слишком короткий») — наружу.
        detail = response.json().get("detail", "Změna hesla selhala.")
        raise ProfileError(400, detail)
    if response.status_code != 200:
        raise ProfileError(response.status_code, "Změna hesla selhala.")


def logout(db: Session) -> None:
    """Удаляет синглтон-строку — следующий старт UI покажет экран логина."""
    session = db.get(AuthSession, 1)
    if session is not None:
        db.delete(session)
        db.commit()


def verify_with_server(token: str) -> VerifyResult:
    """Дёргает /auth/verify на сервере лицензий. Возвращает результат-метку.

    - status='ok'              — сервер ответил 200, токен валиден.
    - status='revoked'         — 401/403: токен битый/просрочен или юзер отозван.
    - status='update_required' — 426: версия клиента младше MIN_SUPPORTED_VERSION.
                                 download_url присылает сервер.
    - status='offline'         — сервер недоступен (network error / 5xx). Сюда же
                                 попадаем без сети — это и есть «grace period».
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
    return VerifyResult(status="offline")  # 5xx и прочее — «сервер недоступен»


def verify_once() -> None:
    """Одна итерация проверки: обновляет статус сессии в БД.

    Открывает свою сессию SQLAlchemy — мы вне FastAPI-зависимостей (фоновый цикл).
    """
    db = SessionLocal()
    try:
        session = db.get(AuthSession, 1)
        if session is None:
            return  # не залогинен — нечего проверять
        result = verify_with_server(session.token)
        if result.status == "ok":
            session.last_verified_at = datetime.utcnow()
            session.download_url = None
        else:
            # При offline/revoked/update_required НЕ обновляем last_verified_at —
            # счётчик grace-period должен тикать от последнего успешного verify.
            session.download_url = result.download_url
        session.last_verify_status = result.status
        db.commit()
    finally:
        db.close()


async def run_verify_loop() -> None:
    """Фоновая корутина: проверяем токен раз в час, начиная сразу со старта."""
    while True:
        try:
            # httpx — синхронный, не блокируем event loop.
            await asyncio.to_thread(verify_once)
        except Exception as exc:  # pylint: disable=broad-except
            # Лог и продолжаем — цикл важнее любой одной ошибки.
            print(f"[verify_loop] error: {exc}")
        await asyncio.sleep(VERIFY_INTERVAL_SECONDS)


def compute_effective_status(session: AuthSession) -> str:
    """Сводит last_verify_status и возраст last_verified_at в одно решение.

    Возвращает 'ok' или 'blocked'. UI блокируется при 'blocked'.

    - revoked → blocked мгновенно (сервер явно сказал «нет»).
    - offline → blocked, если последний успешный verify был >1 дня назад.
    - ok      → ok.
    """
    if session.last_verify_status in ("revoked", "update_required"):
        return "blocked"
    if session.last_verify_status == "offline":
        age = datetime.utcnow() - session.last_verified_at
        if age > GRACE_PERIOD:
            return "blocked"
    return "ok"
