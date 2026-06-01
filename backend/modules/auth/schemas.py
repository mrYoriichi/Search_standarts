"""Pydantic-схемы модуля auth."""

from datetime import datetime

from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    """Возвращаем username, токен наружу не отдаём — он живёт в БД."""

    username: str


class RegisterRequest(BaseModel):
    """Саморегистрация. Логином служит email. После успеха клиент сразу залогинен
    (тот же LoginResponse). linkedin — единственное необязательное поле."""

    email: str
    password: str
    full_name: str
    company: str
    position: str
    linkedin: str | None = None


class ProfileResponse(BaseModel):
    """Профиль юзера (приходит с сервера лицензий). username — только чтение."""

    username: str
    email: str | None = None
    full_name: str | None = None
    company: str | None = None
    position: str | None = None
    linkedin: str | None = None


class ProfileUpdate(BaseModel):
    """Редактируемые поля профиля."""

    email: str | None = None
    full_name: str | None = None
    company: str | None = None
    position: str | None = None
    linkedin: str | None = None


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


class StatusResponse(BaseModel):
    """Текущее состояние авторизации.

    logged_in=False — нет строки в auth_session.
    logged_in=True  — есть строка; status показывает результат последнего verify.
    effective_status — что показывать UI: 'ok' разрешает работу, 'blocked' блокирует
                       (см. compute_effective_status в service.py).
    """

    logged_in: bool
    username: str | None = None
    status: str | None = None  # 'ok' | 'revoked' | 'offline' | 'update_required'
    effective_status: str | None = None  # 'ok' | 'blocked'
    last_verified_at: datetime | None = None
    # Заполнен, если status='update_required'. Фронт показывает в оверлее
    # «Установите новую версию» как ссылку.
    download_url: str | None = None
