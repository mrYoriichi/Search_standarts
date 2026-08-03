"""Tests of the per-page classifier (drawing vs prose).

Threshold numbers come from live measurements 2026-07-18 (MVL 720, VL4,
a real CAD project).
"""

from pdf_processing.page_router import classify_page


def test_prose_page_is_text():
    # pure prose: no paths, rich text
    assert classify_page(path_count=0, text_len=2000) == "text"


def test_prose_with_embedded_schema_is_text():
    # prose with an embedded diagram: up to ~575 paths, but rich text -> prose
    assert classify_page(path_count=575, text_len=1500) == "text"


def test_vector_drawing_is_drawing():
    # a VL4 drawing: thousands of paths, text flattened into curves (empty)
    assert classify_page(path_count=10315, text_len=0) == "drawing"


def test_cad_drawing_with_text_layer_is_drawing():
    # a CAD drawing with a real text layer: thousands of paths -> still a drawing
    assert classify_page(path_count=116920, text_len=1499) == "drawing"


def test_scanned_page_without_text_is_drawing():
    # a scan: no paths, no text -> OCR
    assert classify_page(path_count=0, text_len=0) == "drawing"


def test_thin_prose_stays_text():
    # a thin prose page (a section divider, ~200 chars) — still prose
    assert classify_page(path_count=0, text_len=200) == "text"
