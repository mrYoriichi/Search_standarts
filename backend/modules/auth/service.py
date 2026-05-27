"""Сервис авторизации: ходим на сервер лицензий, кладём токен в локальную БД.

`AuthSession` — синглтон (id=1). Если строки нет, юзер не залогинен.
"""

import asyncio
import os
from datetime import datetime, timedelta

import httpx
from sqlalchemy.orm import Session

from backend.core.database import SessionLocal
from backend.modules.auth.models import AuthSession

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


def login(db: Session, username: str, password: str) -> AuthSession:
    """Ходит на сервер лицензий, получает JWT, сохраняет в БД синглтоном.

    Если строка уже есть (старый юзер) — перезаписываем.
    """
    try:
        response = httpx.post(
            f"{LICENSE_SERVER_URL}/auth/login",
            json={"username": username, "password": password},
            timeout=HTTP_TIMEOUT,
        )
    except httpx.HTTPError as exc:
        raise LicenseServerUnavailable(str(exc)) from exc

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
        )
        db.add(session)
    else:
        session.token = token
        session.username = username
        session.last_verified_at = datetime.utcnow()
        session.last_verify_status = "ok"
    db.commit()
    db.refresh(session)
    return session


def get_session(db: Session) -> AuthSession | None:
    return db.get(AuthSession, 1)


def logout(db: Session) -> None:
    """Удаляет синглтон-строку — следующий старт UI покажет экран логина."""
    session = db.get(AuthSession, 1)
    if session is not None:
        db.delete(session)
        db.commit()


def verify_with_server(token: str) -> str:
    """Дёргает /auth/verify на сервере лицензий. Возвращает результат-метку.

    - 'ok'      — сервер ответил 200, токен валиден.
    - 'revoked' — 401/403: токен битый/просрочен или юзер отозван (relogin).
    - 'offline' — сервер недоступен (network error / 5xx). Сюда же попадаем,
                  если нет сети — это и есть «работаем по grace period».
    """
    try:
        response = httpx.get(
            f"{LICENSE_SERVER_URL}/auth/verify",
            headers={"Authorization": f"Bearer {token}"},
            timeout=HTTP_TIMEOUT,
        )
    except httpx.HTTPError:
        return "offline"

    if response.status_code == 200:
        return "ok"
    if response.status_code in (401, 403):
        return "revoked"
    return "offline"  # 5xx и всё прочее трактуем как «сервер недоступен»


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
        if result == "ok":
            session.last_verified_at = datetime.utcnow()
            session.last_verify_status = "ok"
        else:
            # При offline/revoked НЕ обновляем last_verified_at —
            # счётчик grace-period должен тикать от последнего успешного verify.
            session.last_verify_status = result
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
    if session.last_verify_status == "revoked":
        return "blocked"
    if session.last_verify_status == "offline":
        age = datetime.utcnow() - session.last_verified_at
        if age > GRACE_PERIOD:
            return "blocked"
    return "ok"
