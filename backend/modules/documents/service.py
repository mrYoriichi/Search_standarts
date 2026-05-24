"""Бизнес-логика модуля documents."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.modules.documents.models import Document


def list_documents(db: Session) -> list[Document]:
    """Все документы из библиотеки, упорядоченные по дате создания."""
    stmt = select(Document).order_by(Document.created_at)
    return list(db.scalars(stmt))
