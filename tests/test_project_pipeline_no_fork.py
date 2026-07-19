"""Шаг 3 универсального пайплайна: развилки sheet/text в архиве больше нет.

Документ даже со старым doc_type='sheet' в БД идёт через общий пайплайн
(main→describe→chunk→index) с document_id=slug, как текстовые.
"""

import json

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import chunk
import describe
import index
import main
from backend.core.database import Base
from backend.modules.projects import pipeline
from backend.modules.projects.models import ProjectDocument
from backend.modules.settings import models as settings_models  # noqa: F401 — таблица settings для create_all
from jsonio import save_json_atomic


def test_sheet_goes_through_common_pipeline(monkeypatch, tmp_path):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    monkeypatch.setattr(pipeline, "SessionLocal", session_factory)
    monkeypatch.setattr(pipeline, "PROJECTS_DATA_DIR", tmp_path)

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

    def fake_parse(
        pdf_name: str,
        pdf_path: str | None = None,
        doc_dir=None,
        document_id: str | None = None,
        pages_dir=None,
    ) -> None:
        recorded["document_id"] = document_id

    def fake_chunk(pdf_name: str, doc_dir=None) -> None:
        doc_dir.mkdir(
            parents=True, exist_ok=True
        )  # в реальном потоке папку создаёт parser-шаг
        save_json_atomic(
            doc_dir / "chunks.json",
            [{"chunk_id": f"{slug}_c000", "document_title": "vykres_202"}],
        )

    monkeypatch.setattr(main, "process", fake_parse)
    monkeypatch.setattr(describe, "process", lambda *args, **kwargs: None)
    monkeypatch.setattr(chunk, "process", fake_chunk)
    monkeypatch.setattr(index, "process", lambda *args, **kwargs: None)

    pipeline.run_project_pipeline(slug, pdf_path=str(tmp_path / "vykres_202.pdf"))

    # Лист прошёл через общий пайплайн со scoped-slug
    assert recorded.get("document_id") == slug
    # _prefix_project_context добавил проект в document_title
    chunks = json.loads((tmp_path / slug / "chunks.json").read_text(encoding="utf-8"))
    assert chunks[0]["document_title"].startswith("Beta_most")
    with session_factory() as db:
        doc = db.scalar(select(ProjectDocument).where(ProjectDocument.slug == slug))
        assert doc.status == "ready"
