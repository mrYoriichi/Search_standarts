"""Тест бага №1 аудита: библиотечный run_pipeline обязан передавать
scoped-slug ({folder_id}__{файл}) в parser-шаг как document_id.

Без этого parser берёт id из имени файла, артефакты в .search_index
получают нескоуп document_id/chunk_id, и фильтр «Kde hledat»
(сравнение со slug из БД) не находит ни одного чанка документа.
Архив проектов передаёт document_id правильно (projects/pipeline.py) —
он здесь образец.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import chunk
import describe
import index
import main
from backend.core.database import Base
from backend.modules.documents import pipeline
from backend.modules.settings import models as settings_models  # noqa: F401 — таблица settings для create_all


@pytest.fixture
def fake_db(monkeypatch):
    """In-memory БД вместо реального app.db: run_pipeline сам открывает сессии."""
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
    ) -> None:
        recorded["document_id"] = document_id

    monkeypatch.setattr(main, "process", fake_parse)
    monkeypatch.setattr(describe, "process", lambda *args, **kwargs: None)
    monkeypatch.setattr(chunk, "process", lambda *args, **kwargs: None)
    monkeypatch.setattr(index, "process", lambda *args, **kwargs: None)
    # Телеметрия пишет в реальный app.db — в тесте глушим
    monkeypatch.setattr(pipeline, "track_event", lambda *args, **kwargs: None)

    slug = "abc123__norma"
    pipeline.run_pipeline(
        slug, pdf_path=str(tmp_path / "Norma.pdf"), doc_dir=tmp_path / "idx"
    )

    assert recorded.get("document_id") == slug
