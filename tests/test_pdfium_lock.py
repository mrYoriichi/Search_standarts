"""Замок PDFium должен быть общим с Docling.

Docling рендерит через pypdfium2 под собственным замком; если наш замок —
другой объект, наши рендеры продолжают гоняться с его рендерами. Тест
упадёт, когда Docling переложит внутренний модуль и сработает откат.
"""


def test_lock_is_docling_lock():
    from docling.utils.locks import pypdfium2_lock

    from pdf_processing.pdfium_lock import PDFIUM_LOCK

    assert PDFIUM_LOCK is pypdfium2_lock
