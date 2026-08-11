"""Universal pipeline step 3: no more sheet/text fork in the archive.

Even a document with the old doc_type='sheet' in the DB goes through the
shared pipeline (main->describe->chunk->index) with document_id=slug,
like text documents.
"""

import json

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from pipeline import chunk, describe, embed
from backend.core import parse_subprocess
from backend.core.database import Base
from backend.modules.projects import pipeline
from backend.modules.projects.models import ProjectDocument
from backend.modules.settings import models as settings_models  # noqa: F401 — settings table for create_all
from common.jsonio import save_json_atomic


def test_sheet_goes_through_common_pipeline(monkeypatch, tmp_path):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    monkeypatch.setattr(pipeline, "SessionLocal", session_factory)
    root = tmp_path / "Beta_most"
    root.mkdir()

    slug = "beta_most__vykres_202"
    with session_factory() as db:
        db.add(
            ProjectDocument(
                slug=slug,
                project="Beta_most",
                relative_path="Beta_most/vykresy/vykres_202.pdf",
                doc_type="sheet",
                page_count=1,
                status="pending",
            )
        )
        db.commit()

    recorded: dict[str, str | None] = {}

    def fake_run_parse(
        parse_slug: str,
        pdf_path: str | None,
        doc_dir=None,
        pages_dir=None,
        on_text_pages=None,
        on_drawing_page=None,
        should_cancel=None,
    ) -> None:
        recorded["slug"] = parse_slug

    def fake_chunk(pdf_name: str, doc_dir=None) -> None:
        doc_dir.mkdir(
            parents=True, exist_ok=True
        )  # in the real flow the parser step creates the folder
        save_json_atomic(
            doc_dir / "chunks.json",
            [{"chunk_id": f"{slug}_c000", "document_title": "vykres_202"}],
        )

    monkeypatch.setattr(parse_subprocess, "run_parse", fake_run_parse)
    monkeypatch.setattr(describe, "process", lambda *args, **kwargs: None)
    monkeypatch.setattr(chunk, "process", fake_chunk)
    monkeypatch.setattr(embed, "process", lambda *args, **kwargs: None)

    pipeline.run_project_pipeline(
        slug, pdf_path=str(root / "vykresy" / "vykres_202.pdf"), root=str(root)
    )

    # The sheet went through the shared pipeline with the scoped slug
    assert recorded.get("slug") == slug
    # Artifacts land in the project folder itself (<root>/.search_index),
    # and _prefix_project_context added the project to document_title
    chunks = json.loads(
        (root / ".search_index" / slug / "chunks.json").read_text(encoding="utf-8")
    )
    assert chunks[0]["document_title"].startswith("Beta_most")
    with session_factory() as db:
        doc = db.scalar(select(ProjectDocument).where(ProjectDocument.slug == slug))
        assert doc.status == "ready"
