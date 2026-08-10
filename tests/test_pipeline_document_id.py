"""Test of audit bug #1: the library run_pipeline must pass the scoped
slug ({folder_id}__{file}) into the parse stage.

Without it the parser takes the id from the file name, artifacts in
.search_index get unscoped document_id/chunk_id, and the "Kde hledat"
filter (comparison with the DB slug) finds none of the document's chunks.
Parse now runs in a worker process: the pipeline passes the slug to
run_parse, and the worker stamps it as document_id (tested in
test_parse_worker).
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pipeline import chunk, describe, embed
from backend.core import parse_subprocess
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

    def fake_run_parse(
        slug: str,
        pdf_path: str | None,
        doc_dir=None,
        pages_dir=None,
        on_text_pages=None,
        on_drawing_page=None,
    ) -> None:
        recorded["slug"] = slug

    monkeypatch.setattr(parse_subprocess, "run_parse", fake_run_parse)
    monkeypatch.setattr(describe, "process", lambda *args, **kwargs: None)
    monkeypatch.setattr(chunk, "process", lambda *args, **kwargs: None)
    monkeypatch.setattr(embed, "process", lambda *args, **kwargs: None)
    # Telemetry writes to the real app.db — silenced in the test
    monkeypatch.setattr(pipeline, "track_event", lambda *args, **kwargs: None)

    slug = "abc123__norma"
    pipeline.run_pipeline(
        slug, pdf_path=str(tmp_path / "Norma.pdf"), doc_dir=tmp_path / "idx"
    )

    assert recorded.get("slug") == slug
