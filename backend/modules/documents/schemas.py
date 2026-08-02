"""Pydantic schemas for the documents endpoints."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DocumentResponse(BaseModel):
    """One document in the API response — what the library list shows."""

    # from_attributes=True lets Pydantic read fields straight off the ORM
    # model — returning Document(...) serializes without manual mapping.
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    title: str
    status: str
    error_message: str | None = None
    pinned: bool
    created_at: datetime
