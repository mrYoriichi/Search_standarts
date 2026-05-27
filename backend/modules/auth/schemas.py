"""Pydantic-схемы модуля auth."""

from datetime import datetime

from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    """Возвращаем username, токен наружу не отдаём — он живёт в БД."""

    username: str


class StatusResponse(BaseModel):
    """Текущее состояние авторизации.

    logged_in=False — нет строки в auth_session.
    logged_in=True  — есть строка; status показывает результат последнего verify.
    effective_status — что показывать UI: 'ok' разрешает работу, 'blocked' блокирует
                       (см. compute_effective_status в service.py).
    """

    logged_in: bool
    username: str | None = None
    status: str | None = None  # 'ok' | 'revoked' | 'offline'
    effective_status: str | None = None  # 'ok' | 'blocked'
    last_verified_at: datetime | None = None
