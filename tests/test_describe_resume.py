"""Describe resume tests: a rerun does not pay for what is already described.

Vision is the most expensive pipeline stage. descriptions.json is saved after
every page; a document that failed midway continues from the break point on
rerun instead of buying all descriptions again.
"""

import json

import pypdfium2 as pdfium
import pytest

from pipeline import describe


def _write_document(doc_dir, n_pages: int) -> None:
    doc = {
        "document_name": "Test",
        "document_id": "test",
        "pages": [
            {
                "page_number": i,
                "blocks": [{"type": "figure", "block_id": f"p{i}_b0"}],
            }
            for i in range(1, n_pages + 1)
        ],
    }
    (doc_dir / "document.json").write_text(
        json.dumps(doc, ensure_ascii=False), encoding="utf-8"
    )


def _make_pages(pages_dir, n_pages: int) -> None:
    pages_dir.mkdir(parents=True, exist_ok=True)
    for i in range(1, n_pages + 1):
        (pages_dir / f"p{i:03d}.png").write_bytes(b"fake png")


def _fake_metadata(image, model):
    return {"title": "Titul", "summary": "Souhrn"}, 1, 1


def test_crash_keeps_paid_pages_and_resume_skips_them(tmp_path, monkeypatch):
    _write_document(tmp_path, 3)
    _make_pages(tmp_path / "pages", 3)
    monkeypatch.setattr(describe, "extract_document_metadata", _fake_metadata)

    # First run: page 2 fails (a persistent API error).
    def flaky(document, page_number, image_path, model):
        if page_number == 2:
            raise RuntimeError("API down")
        return {f"p{page_number}_b0": f"popis {page_number}"}, 1, 1

    monkeypatch.setattr(describe, "describe_page_visuals", flaky)
    with pytest.raises(RuntimeError):
        describe.process("test", doc_dir=tmp_path)

    # What was paid for is saved: metadata + page 1.
    saved = json.loads((tmp_path / "descriptions.json").read_text(encoding="utf-8"))
    assert saved["document_title"] == "Titul"
    assert saved["described_pages"] == [1]
    assert saved["block_descriptions"] == {"p1_b0": "popis 1"}

    # Second run: the API is back. Page 1 and metadata are not bought again.
    calls: list[int] = []

    def ok(document, page_number, image_path, model):
        calls.append(page_number)
        return {f"p{page_number}_b0": f"popis {page_number}"}, 1, 1

    def metadata_must_not_run(image, model):
        raise AssertionError("metadata already present — a repeat call = overpaying")

    monkeypatch.setattr(describe, "describe_page_visuals", ok)
    monkeypatch.setattr(describe, "extract_document_metadata", metadata_must_not_run)
    describe.process("test", doc_dir=tmp_path)

    assert calls == [2, 3]
    final = json.loads((tmp_path / "descriptions.json").read_text(encoding="utf-8"))
    assert set(final["block_descriptions"]) == {"p1_b0", "p2_b0", "p3_b0"}
    assert sorted(final["described_pages"]) == [1, 2, 3]


def test_describe_drawings_skips_already_paid(tmp_path, monkeypatch):
    pdf_path = tmp_path / "vykres.pdf"
    pdf = pdfium.PdfDocument.new()
    pdf.new_page(2000, 1000)
    pdf.new_page(2000, 1000)
    pdf.save(pdf_path)

    document = {
        "pages": [
            {"page_number": 1, "page_type": "drawing", "blocks": []},
            {"page_number": 2, "page_type": "drawing", "blocks": []},
        ]
    }
    calls: list[str] = []

    def fake_describe_drawing(png, model):
        calls.append(str(png))
        return "popis", 1, 1

    monkeypatch.setattr(describe, "describe_drawing", fake_describe_drawing)
    # Test pages are empty — disable the empty-page filter, resume is tested here.
    monkeypatch.setattr(describe, "_is_blank", lambda img: False)

    descriptions = {"1": "už zaplaceno"}
    saves: list[dict] = []
    describe.describe_drawings(
        document,
        str(pdf_path),
        "gpt-test",
        descriptions=descriptions,
        on_page_done=lambda: saves.append(dict(descriptions)),
    )
    assert len(calls) == 1  # page 1 skipped — it is already paid for
    assert descriptions == {"1": "už zaplaceno", "2": "popis"}
    assert saves  # progress was saved after every sheet


def test_describe_drawings_reports_progress(tmp_path, monkeypatch):
    # Archive UX (STEP 3): for a drawings-only PDF the describe stage used to
    # hang on a static "popis obrázků…" — per-sheet progress is needed, as the
    # sheet branch ("list N/M") replaced by the shared pipeline used to give.
    pdf_path = tmp_path / "vykres.pdf"
    pdf = pdfium.PdfDocument.new()
    pdf.new_page(2000, 1000)
    pdf.new_page(2000, 1000)
    pdf.save(pdf_path)

    document = {
        "pages": [
            {"page_number": 1, "page_type": "drawing", "blocks": []},
            {"page_number": 2, "page_type": "drawing", "blocks": []},
        ]
    }
    monkeypatch.setattr(
        describe, "describe_drawing", lambda png, model: ("popis", 1, 1)
    )
    monkeypatch.setattr(describe, "_is_blank", lambda img: False)

    progress_calls: list[tuple[int, int]] = []
    describe.describe_drawings(
        document,
        str(pdf_path),
        "gpt-test",
        descriptions={},
        on_progress=lambda done, total: progress_calls.append((done, total)),
    )
    assert progress_calls == [(1, 2), (2, 2)]


def test_blank_drawing_page_not_sent_to_vision(tmp_path, monkeypatch):
    # An empty cover verso used to go to vision (and twice, due to retry).
    pdf_path = tmp_path / "prazdny.pdf"
    pdf = pdfium.PdfDocument.new()
    pdf.new_page(2000, 1000)  # a page without content — uniform color
    pdf.save(pdf_path)

    document = {"pages": [{"page_number": 1, "page_type": "drawing", "blocks": []}]}

    def must_not_run(*args, **kwargs):
        raise AssertionError("an empty page must not go to vision")

    monkeypatch.setattr(describe, "describe_drawing", must_not_run)

    descriptions: dict[str, str] = {}
    describe.describe_drawings(
        document, str(pdf_path), "gpt-test", descriptions=descriptions
    )
    # The "processed" mark is set — a rerun will not pay either.
    assert descriptions == {"1": ""}


def test_metadata_from_drawing_first_page(tmp_path, monkeypatch):
    # The first page is a drawing: no p001.png from Docling, we render from the PDF.
    pdf_path = tmp_path / "vykres.pdf"
    pdf = pdfium.PdfDocument.new()
    pdf.new_page(2000, 1000)
    pdf.save(pdf_path)

    _write_document(tmp_path, 0)  # no pages with figure/table
    doc = {
        "document_name": "Vykres",
        "document_id": "vykres",
        "pages": [{"page_number": 1, "page_type": "drawing", "blocks": []}],
    }
    (tmp_path / "document.json").write_text(
        json.dumps(doc, ensure_ascii=False), encoding="utf-8"
    )
    (tmp_path / "pages").mkdir()

    monkeypatch.setattr(describe, "extract_document_metadata", _fake_metadata)
    monkeypatch.setattr(describe, "describe_drawing", lambda png, model: ("p", 1, 1))
    monkeypatch.setattr(describe, "_is_blank", lambda img: False)

    describe.process("vykres", doc_dir=tmp_path, pdf_path=str(pdf_path))

    saved = json.loads((tmp_path / "descriptions.json").read_text(encoding="utf-8"))
    assert saved["document_title"] == "Titul"  # metadata mined from the render


def test_no_llm_mode_still_writes_empty_passport(tmp_path, monkeypatch):
    _write_document(tmp_path, 1)

    def must_not_run(*args, **kwargs):
        raise AssertionError("the No-LLM mode must not call vision")

    monkeypatch.setattr(describe, "extract_document_metadata", must_not_run)
    monkeypatch.setattr(describe, "describe_page_visuals", must_not_run)
    describe.process("test", doc_dir=tmp_path, describe_images=False)

    saved = json.loads((tmp_path / "descriptions.json").read_text(encoding="utf-8"))
    assert saved["block_descriptions"] == {}
    assert saved["document_title"] == ""


def test_no_llm_mode_keeps_paid_descriptions(tmp_path, monkeypatch):
    # Shared folder: a colleague already paid for the vision descriptions.
    # Our rerun in No-LLM mode must not overwrite them with an empty passport.
    _write_document(tmp_path, 1)
    paid = {
        "document_title": "Paid",
        "document_summary": "",
        "block_descriptions": {"b1": "drahý popis"},
        "drawing_descriptions": {},
    }
    (tmp_path / "descriptions.json").write_text(
        json.dumps(paid, ensure_ascii=False), encoding="utf-8"
    )

    def must_not_run(*args, **kwargs):
        raise AssertionError("the No-LLM mode must not call vision")

    monkeypatch.setattr(describe, "extract_document_metadata", must_not_run)
    monkeypatch.setattr(describe, "describe_page_visuals", must_not_run)
    describe.process("test", doc_dir=tmp_path, describe_images=False)

    saved = json.loads((tmp_path / "descriptions.json").read_text(encoding="utf-8"))
    assert saved["document_title"] == "Paid"
    assert saved["block_descriptions"] == {"b1": "drahý popis"}
