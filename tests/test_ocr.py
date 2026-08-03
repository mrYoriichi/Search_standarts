"""Tests of parsing the RapidOCR response (OCR itself not run — pulls models)."""

import sys
import time
import types
from concurrent.futures import ThreadPoolExecutor

import pdf_processing.ocr as ocr
from pdf_processing.ocr import _extract_text


class _Result:
    """A stub of the new RapidOCR API: an object with a txts field."""

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


def test_engine_created_once_under_threads(monkeypatch):
    """Windows race: parallel engine creation broke model loading.

    Three threads call _get_engine at once — the engine must be created
    exactly once, the other threads wait and get the same object.
    """
    created: list[int] = []

    class _SlowEngine:
        def __init__(self) -> None:
            created.append(1)
            time.sleep(0.05)  # simulates the slow .onnx model loading

    fake_rapidocr = types.SimpleNamespace(RapidOCR=_SlowEngine)
    monkeypatch.setitem(sys.modules, "rapidocr", fake_rapidocr)
    monkeypatch.setattr(ocr, "_engine", None)

    with ThreadPoolExecutor(max_workers=3) as pool:
        engines = list(pool.map(lambda _: ocr._get_engine(), range(3)))

    assert len(created) == 1
    assert engines[0] is engines[1] is engines[2]
