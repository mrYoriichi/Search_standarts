"""Тесты дозаписи describe: повторный запуск не платит за уже описанное.

Vision — самый дорогой этап пайплайна. descriptions.json сохраняется после
каждой страницы; упавший на середине документ при повторном запуске
продолжает с места обрыва, а не покупает все описания заново.
"""

import json

import pypdfium2 as pdfium
import pytest

import describe


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

    # Первый запуск: страница 2 падает (устойчивая ошибка API).
    def flaky(document, page_number, image_path, model):
        if page_number == 2:
            raise RuntimeError("API down")
        return {f"p{page_number}_b0": f"popis {page_number}"}, 1, 1

    monkeypatch.setattr(describe, "describe_page_visuals", flaky)
    with pytest.raises(RuntimeError):
        describe.process("test", doc_dir=tmp_path)

    # Оплаченное сохранено: метаданные + страница 1.
    saved = json.loads((tmp_path / "descriptions.json").read_text(encoding="utf-8"))
    assert saved["document_title"] == "Titul"
    assert saved["described_pages"] == [1]
    assert saved["block_descriptions"] == {"p1_b0": "popis 1"}

    # Второй запуск: API ожил. Страницу 1 и метаданные не покупаем снова.
    calls: list[int] = []

    def ok(document, page_number, image_path, model):
        calls.append(page_number)
        return {f"p{page_number}_b0": f"popis {page_number}"}, 1, 1

    def metadata_must_not_run(image, model):
        raise AssertionError("метаданные уже есть — повторный вызов = переплата")

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

    descriptions = {"1": "už zaplaceno"}
    saves: list[dict] = []
    describe.describe_drawings(
        document,
        str(pdf_path),
        "gpt-test",
        descriptions=descriptions,
        on_page_done=lambda: saves.append(dict(descriptions)),
    )
    assert len(calls) == 1  # страница 1 пропущена — за неё уже заплачено
    assert descriptions == {"1": "už zaplaceno", "2": "popis"}
    assert saves  # прогресс сохранялся после каждого листа


def test_no_llm_mode_still_writes_empty_passport(tmp_path, monkeypatch):
    _write_document(tmp_path, 1)

    def must_not_run(*args, **kwargs):
        raise AssertionError("режим «без LLM» не должен звать vision")

    monkeypatch.setattr(describe, "extract_document_metadata", must_not_run)
    monkeypatch.setattr(describe, "describe_page_visuals", must_not_run)
    describe.process("test", doc_dir=tmp_path, describe_images=False)

    saved = json.loads((tmp_path / "descriptions.json").read_text(encoding="utf-8"))
    assert saved["block_descriptions"] == {}
    assert saved["document_title"] == ""
