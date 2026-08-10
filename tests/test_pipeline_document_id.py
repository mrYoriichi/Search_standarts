"""Test of audit bug #1: the library run_pipeline must pass the scoped
slug ({folder_id}__{file}) into the parser step as document_id.

Without it the parser takes the id from the file name, artifacts in
.search_index get unscoped document_id/chunk_id, and the "Kde hledat"
filter (comparison with the DB slug) finds none of the document's chunks.
The project archive passes document_id correctly (projects/pipeline.py) —
it is the reference here.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pipeline import chunk, describe, embed, parse
from backend.core.database import Base
from backend.modules.documents import pipeline
from backend.modules.settings import models as settings_models  # noqa: F401 — settings table for create_all


@pytest.fixture
def fake_db(monkeypatch):
    """In-memory DB instead of the real app.db: run_pipeline opens its own sessions."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(pipeline, "SessionLocal", sessionmaker(bind=engine))


def test_run_pipeline_passes_scoped_document_id(fake_db, monkeypatch, tmp_path):
    recorded: dict[str, str | None] = {}

    def fake_parse(
        pdf_name: str,
        pdf_path: str | None = None,
        doc_dir=None,
        document_id: str | None = None,
        pages_dir=None,
        on_text_pages=None,
        on_drawing_page=None,
    ) -> None:
        recorded["document_id"] = document_id

    monkeypatch.setattr(parse, "process", fake_parse)
    monkeypatch.setattr(describe, "process", lambda *args, **kwargs: None)
    monkeypatch.setattr(chunk, "process", lambda *args, **kwargs: None)
    monkeypatch.setattr(embed, "process", lambda *args, **kwargs: None)
    # Telemetry writes to the real app.db — silenced in the test
    monkeypatch.setattr(pipeline, "track_event", lambda *args, **kwargs: None)

    slug = "abc123__norma"
    pipeline.run_pipeline(
        slug, pdf_path=str(tmp_path / "Norma.pdf"), doc_dir=tmp_path / "idx"
    )

    assert recorded.get("document_id") == slug
