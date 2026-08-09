"""Pydantic schemas for the Question → Answer endpoint.

The JSON shapes in (what the frontend sends) and out (what we return).
FastAPI validates against them and builds /docs.
"""

from typing import Literal

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    """Frontend request: question + optional document filter + search mode."""

    question: str = Field(..., min_length=1, description="The question text")
    document_ids: list[str] | None = Field(
        default=None,
        description="Document slugs to filter by. None = search the whole library.",
    )
    mode: Literal["hybrid", "vector", "keyword"] = Field(
        default="hybrid",
        description="Search mode: hybrid (7 vector + 7 BM25), vector (top-20), keyword (top-10 BM25).",
    )
    answer_model: Literal["gpt-5.6-luna", "gpt-5.6-sol"] = Field(
        default="gpt-5.6-luna",
        description="Answer-generation model.",
    )
    expand: bool = Field(
        default=True,
        description="Expand the query via LLM (diacritics/synonyms) before searching.",
    )
    strong: bool = Field(
        default=False,
        description="Strong search: attach page snapshots of the top sources "
        "to the answering LLM (pricier and slower, for hard questions).",
    )
    answer_language: Literal["cs", "en", "de"] | None = Field(
        default=None,
        description="LLM answer language. None — use the stored setting "
        "(/api/settings/answer-language).",
    )


class UsedChunk(BaseModel):
    """A fragment the model actually relied on — with full text.

    Needed for "Report" complaints (F7): shows what the model read."""

    chunk_id: str
    document: str
    section: str
    pages: list[int]
    text: str


class FlagRequest(BaseModel):
    """The "Report" flag: the user says the answer is wrong or missing.

    The text comes straight from the frontend (already shown to the
    user) — no need to touch QueryLog. note — the optional remark;
    used_chunks — the fragments the model used (with text)."""

    question: str = Field(..., min_length=1)
    answer: str
    answer_model: str | None = None
    note: str | None = None
    used_chunks: list[UsedChunk] = Field(default_factory=list)


class Source(BaseModel):
    """One source: which document/section/pages the answer relied on."""

    document: str
    slug: str  # document id — the frontend builds the PDF link from it
    section: str
    pages: list[int]


class AskResponse(BaseModel):
    """Endpoint response: text + sources + the QueryLog row id."""

    answer: str
    sources: list[Source]
    related_sources: list[Source]  # relevant but not directly used
    # Used fragments with text — the frontend returns them on "Report".
    used_chunks: list[UsedChunk]
    query_log_id: int
    search_query: str  # the expanded query actually searched (shown to the user)
    answer_model: str  # the model that generated the answer
    answer_ms: int  # answer-generation time, ms (for model comparison)
