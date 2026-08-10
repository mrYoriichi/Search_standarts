"""Резюм parse: целый document.json + неизменённый PDF = без Docling/OCR.

Живой случай 2026-08-10: describe упал на 200-й странице 769-страничного
документа, а повторный запуск заново парсил весь PDF час — хотя готовый
document.json лежал в артефактах. Резюм пропускает Docling/OCR целиком
и только пере-рендерит скриншоты нужных страниц через pdfium.
"""

import json
from pathlib import Path

import pypdfium2 as pdfium
import pytest

from common.jsonio import save_json_atomic
from pipeline import parse


def _make_pdf(path: Path, n_pages: int = 2) -> None:
    doc = pdfium.PdfDocument.new()
    for _ in range(n_pages):
        doc.new_page(200, 100)
    with open(path, "wb") as f:
        doc.save(f)


def _make_document(document_id: str, source: dict | None) -> dict:
    # Страница 2 несёт figure — она (плюс всегда страница 1) должна
    # получить скриншот при резюме.
    document = {
        "document_id": document_id,
        "document_name": f"{document_id}.pdf",
        "pages": [
            {"page_number": 1, "page_text": "text", "blocks": []},
            {
                "page_number": 2,
                "page_text": "",
                "blocks": [{"block_id": "p2_b01", "type": "figure"}],
            },
        ],
    }
    if source is not None:
        document["source"] = source
    return document


@pytest.fixture()
def pdf_path(tmp_path):
    path = tmp_path / "doc.pdf"
    _make_pdf(path)
    return path


def test_resume_skips_parse_and_rerenders_pages(tmp_path, pdf_path, monkeypatch):
    doc_dir = tmp_path / "artifacts"
    doc_dir.mkdir()
    document = _make_document("slug1", parse._source_stat(str(pdf_path)))
    save_json_atomic(doc_dir / "document.json", document)
    before = (doc_dir / "document.json").stat().st_mtime_ns

    def boom(*args, **kwargs):
        raise AssertionError("full parse must not run on resume")

    monkeypatch.setattr(parse, "_full_parse", boom)
    pages_dir = tmp_path / "pages"
    parse.process(
        "slug1",
        pdf_path=str(pdf_path),
        doc_dir=doc_dir,
        document_id="slug1",
        pages_dir=pages_dir,
    )
    # Скриншоты: страница с figure + всегда страница 1.
    assert sorted(p.name for p in pages_dir.iterdir()) == ["p001.png", "p002.png"]
    # document.json не перезаписан — оплаченные артефакты не трогаем.
    assert (doc_dir / "document.json").stat().st_mtime_ns == before


@pytest.mark.parametrize(
    "spoil",
    ["no_document_json", "corrupt_json", "no_source", "stale_source", "other_id"],
)
def test_full_parse_runs_when_not_resumable(tmp_path, pdf_path, monkeypatch, spoil):
    doc_dir = tmp_path / "artifacts"
    doc_dir.mkdir()
    source = parse._source_stat(str(pdf_path))
    if spoil == "stale_source":
        source["file_mtime"] += 1  # PDF менялся после парсинга
    document = _make_document(
        "other" if spoil == "other_id" else "slug1",
        None if spoil == "no_source" else source,
    )
    if spoil == "corrupt_json":
        (doc_dir / "document.json").write_text("{broken", encoding="utf-8")
    elif spoil != "no_document_json":
        save_json_atomic(doc_dir / "document.json", document)

    calls = []
    monkeypatch.setattr(parse, "_full_parse", lambda *a, **kw: calls.append(a))
    parse.process("slug1", pdf_path=str(pdf_path), doc_dir=doc_dir, document_id="slug1")
    assert len(calls) == 1


def test_source_stat_survives_json_roundtrip(tmp_path, pdf_path):
    # source пишется в document.json — после json-цикла сравнение точное.
    source = parse._source_stat(str(pdf_path))
    assert json.loads(json.dumps(source)) == source
