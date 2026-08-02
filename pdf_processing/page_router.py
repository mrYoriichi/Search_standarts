"""Per-page router: drawing or text page.

A page is a drawing when vector geometry dominates (PATH object count)
OR there is no extractable text layer. Published drawings come either as
thousands of vector paths (text flattened into curves) or as scans with
no text — both need OCR, not heading-based chunking.

The threshold was picked on real pages (measured 2026-07-18): prose even
with an embedded scheme ≤ 575 paths, drawings 3200–116000. Frozen by a
test.
"""

import pypdfium2 as pdfium

from pdf_processing.pdfium_lock import PDFIUM_LOCK

# Above this many vector paths the page counts as a drawing.
PATH_DOMINANT_THRESHOLD = 1000
# Below this much text in the layer we treat the page as having no
# extractable text (scan/curves).
MIN_TEXT_LAYER_CHARS = 50

# pdfium object type: 2 = vector path (FPDF_PAGEOBJ_PATH).
_PATH_OBJ_TYPE = 2


def count_paths(page: "pdfium.PdfPage") -> int:
    """Number of vector paths on the page — the geometry 'drawingness' measure."""
    return sum(1 for obj in page.get_objects() if obj.type == _PATH_OBJ_TYPE)


def classify_page(path_count: int, text_len: int) -> str:
    """Page type: 'drawing' (OCR) or 'text' (heading-based chunking)."""
    if path_count > PATH_DOMINANT_THRESHOLD or text_len < MIN_TEXT_LAYER_CHARS:
        return "drawing"
    return "text"


def classify_pages(pdf_path: str) -> list[str]:
    """Type of every PDF page in order: a list of 'drawing' | 'text'."""
    with PDFIUM_LOCK:
        doc = pdfium.PdfDocument(pdf_path)
        try:
            result: list[str] = []
            for i in range(len(doc)):
                page = doc[i]
                text_len = len(page.get_textpage().get_text_range().strip())
                result.append(classify_page(count_paths(page), text_len))
            return result
        finally:
            doc.close()
