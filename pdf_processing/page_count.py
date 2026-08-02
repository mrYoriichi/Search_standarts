"""Число страниц PDF — под общим замком PDFium (см. pdfium_lock)."""

from pathlib import Path

import pypdfium2 as pdfium

from pdf_processing.pdfium_lock import PDFIUM_LOCK


def count_pages(pdf_path: Path) -> int:
    """Число страниц PDF (для UI и лимита) + бесплатный отсев битых файлов.

    Кидает исключение, если файл не открывается как PDF, —
    обрабатывает вызывающий.
    """
    with PDFIUM_LOCK:
        doc = pdfium.PdfDocument(pdf_path)
        try:
            return len(doc)
        finally:
            doc.close()
