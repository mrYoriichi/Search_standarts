"""Тесты склейки текста чертёжной страницы (рендер/OCR не запускаем)."""

from pdf_processing.drawing import build_drawing_text


def test_combines_layer_and_ocr():
    assert build_drawing_text("rozpiska", "OCR LABELS") == "rozpiska\n\nOCR LABELS"


def test_empty_layer_keeps_ocr():
    # чертёж VL4: текстовый слой пуст → остаётся только OCR
    assert build_drawing_text("", "OCR ONLY") == "OCR ONLY"


def test_empty_ocr_keeps_layer():
    assert build_drawing_text("LAYER ONLY", "") == "LAYER ONLY"


def test_both_empty_is_empty():
    assert build_drawing_text("", "") == ""


def test_whitespace_only_is_empty():
    assert build_drawing_text("  ", "\n") == ""
