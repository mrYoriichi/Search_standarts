"""Модель Document — метаданные документа в локальной библиотеке.

Сам PDF, чанки и эмбеддинги остаются на диске в data/raw_data/{slug}/.
БД хранит только метаданные + указатель slug на папку.
"""

from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.database import Base


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(unique=True)  # имя папки в data/raw_data/
    # Путь PDF относительно library_path (например, "MVL/649.pdf").
    # None у старых записей, заполняется при сканировании.
    relative_path: Mapped[str | None] = mapped_column(default=None)
    title: Mapped[str]
    # Тип исходника: pdf сейчас; docx/xlsx/dwg/... — в будущих pipeline.
    source_type: Mapped[str] = mapped_column(default="pdf")
    status: Mapped[str] = mapped_column(default="processing")
    # Если pipeline упал — кладём сюда текст ошибки. У готовых документов None.
    error_message: Mapped[str | None] = mapped_column(default=None)
    # Закреплён юзером — показывать в отдельной секции «Закреплённые» сверху.
    pinned: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
