"""Ready-page counters for the UI (the hard page limit was removed 2026-08-06).

The search cache loads every ready index fully into RAM, so the page total
is the number to watch as a library grows (measured 2026-08-02: ~76 KB
steady / ~140 KB peak per chunk, ~1.5 chunks per page). Instead of a hard
limit the app shows a live counter; a memory estimate with a threshold
comes after a measurement on a real big library.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.modules.documents.models import Document
from backend.modules.projects.models import ProjectDocument


def library_pages(db: Session) -> int:
    """Total pages of ready library documents. NULL page_count counts as 0."""
    return int(
        db.scalar(
            select(func.coalesce(func.sum(Document.page_count), 0)).where(
                Document.status == "ready"
            )
        )
    )


def archive_pages(db: Session) -> int:
    """Total pages of ready archive documents. NULL page_count counts as 0."""
    return int(
        db.scalar(
            select(func.coalesce(func.sum(ProjectDocument.page_count), 0)).where(
                ProjectDocument.status == "ready"
            )
        )
    )
