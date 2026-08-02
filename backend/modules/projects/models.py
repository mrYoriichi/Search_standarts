"""Model of a project archive document.

A separate table (not documents): the archive has its own identity
slug = {project}__{file name} and a link to the project.
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.database import Base, naive_utcnow


class ProjectDocument(Base):
    __tablename__ = "project_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String, unique=True, index=True)
    project: Mapped[str] = mapped_column(
        String, index=True
    )  # top-level folder, e.g. "Beta_most"
    relative_path: Mapped[str] = mapped_column(String)  # path inside the archive
    doc_type: Mapped[str] = mapped_column(
        String
    )  # legacy: always "text" (sheet/text fork removed; NOT NULL in live DBs)
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(
        String, default="pending"
    )  # pending|processing|ready|error
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    # PDF stat at indexing time: the scan compares it and resets a replaced
    # file to pending. NULL — a row from an old version (first scan fills it).
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    file_mtime: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=naive_utcnow)
