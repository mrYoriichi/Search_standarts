"""Модель PendingEvent — локальная очередь телеметрии перед отправкой.

Складываем сюда события через `track_event()`. Фоновая корутина
`run_telemetry_sender` берёт батч, шлёт на сервер лицензий, при успехе удаляет.

Если сервер недоступен или юзер не залогинен — события копятся, ничего не теряется.
"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.database import Base


class PendingEvent(Base):
    __tablename__ = "pending_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String)
    # SQLAlchemy сериализует dict ↔ JSON автоматом (TEXT в SQLite).
    props: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Время события у клиента (когда оно реально случилось).
    client_timestamp: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )


class PendingReport(Base):
    """Очередь отчётов «Nahlásit» (F7): помеченный юзером плохой/ненайденный ответ.

    Отдельная от PendingEvent — это персональные данные, складываем сюда ТОЛЬКО
    когда юзер явно нажал «Nahlásit» на ответе. Sender шлёт на /telemetry/flagged
    и при успехе удаляет. note — необязательная заметка юзера («почему не так»).
    """

    __tablename__ = "pending_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    question: Mapped[str] = mapped_column(String)
    answer: Mapped[str] = mapped_column(String)
    answer_model: Mapped[str | None] = mapped_column(String, nullable=True)
    note: Mapped[str | None] = mapped_column(String, nullable=True)
    # Использованные фрагменты (с текстом) — list[dict]. SQLAlchemy ↔ JSON сам.
    chunks: Mapped[list | None] = mapped_column(JSON, nullable=True)
    client_timestamp: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
