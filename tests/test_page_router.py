"""Тесты по-страничного классификатора (чертёж vs проза).

Цифры порогов — из живых замеров 2026-07-18 (MVL 720, VL4, gama).
"""

from pdf_processing.page_router import classify_page


def test_prose_page_is_text():
    # чистая проза: путей нет, текст богатый
    assert classify_page(path_count=0, text_len=2000) == "text"


def test_prose_with_embedded_schema_is_text():
    # проза со встроенной схемой: путей до ~575, но текст богатый → проза
    assert classify_page(path_count=575, text_len=1500) == "text"


def test_vector_drawing_is_drawing():
    # чертёж VL4: тысячи путей, текст сплющён в кривые (пусто)
    assert classify_page(path_count=10315, text_len=0) == "drawing"


def test_cad_drawing_with_text_layer_is_drawing():
    # CAD-чертёж gama с настоящим текстовым слоем: путей тысячи → всё равно чертёж
    assert classify_page(path_count=116920, text_len=1499) == "drawing"


def test_scanned_page_without_text_is_drawing():
    # скан: ни путей, ни текста → OCR
    assert classify_page(path_count=0, text_len=0) == "drawing"


def test_thin_prose_stays_text():
    # тонкая прозаическая страница (раздел-разделитель, ~200 симв.) — ещё проза
    assert classify_page(path_count=0, text_len=200) == "text"
