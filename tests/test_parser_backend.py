"""Гард: docling собирается с читалкой pypdfium2, не с дефолтной.

Дефолтный бэкенд docling-parse на Windows течёт по памяти на документах
с большим числом текстовых страниц (TP100, 188 стр. → 24 ГБ и заморозка;
docling issue #3671). Бэкенд pypdfium2 этого дефекта не имеет, качество
парсинга сравнили на реальных документах — не хуже.
"""

import pytest

from pdf_processing import parser


class _Boom(Exception):
    """Останавливает parse_pdf сразу после создания конвертера."""


def test_parse_pdf_uses_pdfium_backend(monkeypatch):
    captured: dict = {}

    def fake_converter(format_options):
        captured.update(format_options)
        raise _Boom

    monkeypatch.setattr(parser, "DocumentConverter", fake_converter)
    with pytest.raises(_Boom):
        parser.parse_pdf("whatever.pdf")

    from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend
    from docling.datamodel.base_models import InputFormat

    assert captured[InputFormat.PDF].backend is PyPdfiumDocumentBackend
