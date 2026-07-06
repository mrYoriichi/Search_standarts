"""Модель документа архива проектов.

Отдельная таблица (не documents): у архива своя идентичность
slug = {проект}__{имя файла} и привязка к проекту.
"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.database import Base


class ProjectDocument(Base):
    __tablename__ = "project_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String, unique=True, index=True)
    project: Mapped[str] = mapped_column(String, index=True)      # папка 1-го уровня, напр. "Beta_most"
    relative_path: Mapped[str] = mapped_column(String)            # путь внутри архива
    doc_type: Mapped[str] = mapped_column(String)                 # "text" (TZ, статика) | "sheet" (чертёжный лист)
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String, default="pending")  # pending|processing|ready|error
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
