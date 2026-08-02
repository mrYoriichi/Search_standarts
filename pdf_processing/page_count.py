"""PDF page count — under the shared PDFium lock (see pdfium_lock)."""

from pathlib import Path

import pypdfium2 as pdfium

from pdf_processing.pdfium_lock import PDFIUM_LOCK


def count_pages(pdf_path: Path) -> int:
    """Page count of a PDF (for the UI and the page limit) + a free
    check that weeds out broken files.

    Raises when the file cannot be opened as a PDF — the caller handles it.
    """
    with PDFIUM_LOCK:
        doc = pdfium.PdfDocument(pdf_path)
        try:
            return len(doc)
        finally:
            doc.close()
