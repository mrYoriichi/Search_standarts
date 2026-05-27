"""Модель AuthSession — локальное состояние авторизации.

Хранится одна строка-синглтон (id=1). Если строки нет — юзер не залогинен.
Поля:
  - token: JWT от сервера лицензий
  - username: логин юзера (для отображения в UI)
  - last_verified_at: время последнего успешного verify на сервере
  - last_verify_status: 'ok' | 'revoked' | 'offline'
        ok       — сервер ответил 200, токен валиден
        revoked  — сервер ответил 401/403, доступ отозван (мгновенный блок)
        offline  — сервер недоступен (network error / 5xx); работаем,
                   пока last_verified_at не старше 1 дня (grace period)
"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.database import Base


class AuthSession(Base):
    __tablename__ = "auth_session"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token: Mapped[str] = mapped_column(String)
    username: Mapped[str] = mapped_column(String)
    last_verified_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    last_verify_status: Mapped[str] = mapped_column(String, default="ok")
    # Если сервер прислал 426 — кладём сюда URL, фронт покажет в оверлее
    # «Установите новую версию». Иначе остаётся NULL.
    download_url: Mapped[str | None] = mapped_column(String, nullable=True)
