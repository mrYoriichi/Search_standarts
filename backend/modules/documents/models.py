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
    title: Mapped[str]
    # Тип исходника: pdf сейчас; docx/xlsx/dwg/... — в будущих pipeline.
    source_type: Mapped[str] = mapped_column(default="pdf")
    status: Mapped[str] = mapped_column(default="processing")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
