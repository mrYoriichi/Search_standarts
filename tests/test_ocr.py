"""Тесты разбора ответа RapidOCR (сам OCR не запускаем — тянет модели)."""

from pdf_processing.ocr import _extract_text


class _Result:
    """Заглушка нового API RapidOCR: объект с полем txts."""

    def __init__(self, txts):
        self.txts = txts


def test_none_result_is_empty():
    assert _extract_text(None) == ""


def test_new_api_joins_fragments():
    assert _extract_text(_Result(["MADLO", "PRICLE"])) == "MADLO PRICLE"


def test_new_api_empty_is_empty():
    assert _extract_text(_Result(None)) == ""
    assert _extract_text(_Result([])) == ""


def test_old_api_tuple_joins_fragments():
    result = ([[[0, 0], "KAMENNA", 0.9], [[0, 0], "DLAZBA", 0.8]], 0.1)
    assert _extract_text(result) == "KAMENNA DLAZBA"
