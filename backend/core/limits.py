"""Public-build volume limit: 3000 pages (decision 2026-08-02).

The reason is RAM: the search cache loads ALL ready indexes at once
(measured 2026-08-02: ~140 KB peak per chunk while loading; 3000 pages ≈
~630 MB peak — safe even on an 8 GB laptop). It also protects the user's
wallet from accidentally indexing hundreds of pages (vision is paid).

Counted are pages of both tables (library + archive) in ready and
processing states, INCLUDING adopted indexes: RAM does not care who paid.
Pilot builds (PUBLIC_BUILD=False) have no limit.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.modules.documents.models import Document
from backend.modules.projects.models import ProjectDocument
from backend.version import PUBLIC_BUILD

PAGE_LIMIT = 3000


def pages_in_use(db: Session) -> int:
    """Pages already taken by ready and processing documents.

    processing counts too: the document is in the pipeline and will
    become ready — otherwise two consecutive "Index" clicks would bypass
    the limit. NULL page_count (legacy rows) counts as 0.
    """
    statuses = ("ready", "processing")
    library = db.scalar(
        select(func.coalesce(func.sum(Document.page_count), 0)).where(
            Document.status.in_(statuses)
        )
    )
    archive = db.scalar(
        select(func.coalesce(func.sum(ProjectDocument.page_count), 0)).where(
            ProjectDocument.status.in_(statuses)
        )
    )
    return int(library) + int(archive)


def pages_remaining(db: Session) -> int | None:
    """Remaining page budget; None — no limit (pilot build)."""
    if not PUBLIC_BUILD:
        return None
    return max(0, PAGE_LIMIT - pages_in_use(db))
