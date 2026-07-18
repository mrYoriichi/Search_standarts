"""Тесты сборки чанка чертёжного листа проекта (OCR + текстовый слой)."""

from backend.modules.projects.pipeline import build_sheet_chunk


def test_sheet_chunk_includes_ocr_and_layer():
    meta = {
        "objekt": "SO 02 most",
        "cislo": "202.1",
        "nazev": "Půdorys",
        "popis": "Řezy.",
    }
    chunk = build_sheet_chunk(1, meta, "textová vrstva", "OCR LABELS", "")
    assert chunk["ocr_text"] == "OCR LABELS"
    # в текст чанка входят все три источника: описание, слой, OCR
    assert "OCR LABELS" in chunk["text"]
    assert "textová vrstva" in chunk["text"]
    assert "SO 02 most" in chunk["text"]


def test_sheet_chunk_skips_empty_parts():
    # пустой слой и OCR не оставляют лишних пустых строк
    chunk = build_sheet_chunk(1, {"popis": "Popis."}, "", "", "")
    assert chunk["text"] == "Popis."
    assert chunk["ocr_text"] == ""
