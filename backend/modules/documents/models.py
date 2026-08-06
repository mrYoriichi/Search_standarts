"""Document — metadata of a document in the local library.

The PDF itself stays in the user's folder; chunks and embeddings live in
`<folder>/.search_index/{slug}/`. The DB holds only metadata plus the
slug pointer to the folder.
"""

from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.database import Base


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(unique=True)  # artifact folder name
    # PDF path relative to library_path (e.g. "MVL/649.pdf").
    # None on old rows; filled by the scan.
    relative_path: Mapped[str | None] = mapped_column(default=None)
    title: Mapped[str]
    # Source type: pdf today; docx/xlsx/dwg/... in future pipelines.
    source_type: Mapped[str] = mapped_column(default="pdf")
    status: Mapped[str] = mapped_column(default="processing")
    # PDF page count — feeds the page counters (backend/core/page_stats.py).
    # None — legacy row from before the counter; filled on adoption or
    # pipeline submission.
    page_count: Mapped[int | None] = mapped_column(default=None)
    # Error text when the pipeline failed. None on ready documents.
    error_message: Mapped[str | None] = mapped_column(default=None)
    # Pinned by the user — shown in the separate "Pinned" section on top.
    pinned: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
