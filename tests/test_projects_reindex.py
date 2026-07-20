"""Тесты переиндексации документа архива (POST /projects/{slug}/reindex).

Кнопка 🔄 в архиве нужна для живого прогона шага 3: бывшие sheet-документы
переобрабатываются новым общим пайплайном. Зеркало test_documents_guards.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.core.database import Base
from backend.modules.projects import service
from backend.modules.projects.models import ProjectDocument
from backend.modules.projects.pipeline import run_project_pipeline


@pytest.fixture
def db():
    """Чистая in-memory SQLite на каждый тест."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _add_doc(db, slug: str, status: str) -> ProjectDocument:
    doc = ProjectDocument(
        slug=slug,
        project="Most",
        relative_path="Most/TZ.pdf",
        doc_type="text",
        page_count=1,
        status=status,
    )
    db.add(doc)
    db.commit()
    return doc


class _FakeExecutor:
    def __init__(self):
        self.calls = []

    def submit(self, fn, *args):
        self.calls.append((fn, args))


def test_reindex_processing_refused(db):
    _add_doc(db, "most__tz", "processing")
    with pytest.raises(service.DocumentBusyError):
        service.reindex_document(db, "most__tz", paths=[], executor=None)


def test_reindex_unknown_slug_refused(db):
    with pytest.raises(ValueError):
        service.reindex_document(db, "neni", paths=[], executor=None)


def test_reindex_missing_file_refused(db, tmp_path):
    # Файла нет ни в одной папке архива (сетевой диск отвалился / файл удалён).
    _add_doc(db, "most__tz", "ready")
    with pytest.raises(ValueError):
        service.reindex_document(db, "most__tz", paths=[tmp_path], executor=None)


def test_reindex_wipes_artifacts_and_resubmits(db, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "backend.core.paths.PROJECTS_DATA_DIR", tmp_path / "projects_data"
    )
    archive = tmp_path / "archiv"
    (archive / "Most").mkdir(parents=True)
    pdf_path = archive / "Most" / "TZ.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")
    old_artifacts = tmp_path / "projects_data" / "most__tz"
    old_artifacts.mkdir(parents=True)
    (old_artifacts / "chunks.json").write_text("[]", encoding="utf-8")

    doc = _add_doc(db, "most__tz", "error")
    doc.error = "stará chyba"
    db.commit()

    executor = _FakeExecutor()
    result = service.reindex_document(db, "most__tz", [archive], executor)

    assert result.status == "processing"
    assert result.error is None
    assert not old_artifacts.exists()  # старые артефакты снесены
    (fn, args) = executor.calls[0]
    assert fn is run_project_pipeline
    assert args == ("most__tz", str(pdf_path))
