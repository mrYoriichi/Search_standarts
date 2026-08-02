"""Drawing-page processing without vision: text = text layer + OCR.

Published drawings often have an empty text layer (text flattened into
curves) or a partially broken one (title-block form) — OCR recovers what
the layer misses. Both sources are concatenated; dedup/noise cleanup is
deliberately skipped (YAGNI, to be measured on the eval).
"""

import re

import pypdfium2 as pdfium

from pdf_processing.pdfium_lock import PDFIUM_LOCK

# Long render side for OCR. 2200 px proved enough on a large CAD sheet
# (checked live).
RENDER_MAX_SIDE_PX = 2200

# Known Czech design-documentation stages. Longer codes first so "DSPS"
# does not match as "DSP". The drawing title block spells the stage out,
# so we look for the literal word in the sheet text instead of guessing
# from the image (vision confuses stages with nearby codes like D.2.1.4).
_STUPEN_CODES = (
    "DSPS",
    "PDPS",
    "DÚR",
    "DUR",
    "DSP",
    "DPS",
    "RDS",
    "DVZ",
    "ZDS",
    "DZS",
    "DOS",
)
_STUPEN_RE = re.compile(r"\b(" + "|".join(_STUPEN_CODES) + r")\b")


def extract_stupen(text: str) -> str:
    """Design-documentation stage from the sheet text (layer + OCR).

    Returns the first code found (DSP, DÚR, PDPS…) as a whole word, or "".
    """
    match = _STUPEN_RE.search(text)
    return match.group(1) if match else ""


def build_drawing_text(layer_text: str, ocr_text: str) -> str:
    """Chunk text of a drawing page from the PDF text layer and OCR.

    Non-empty sources joined by a blank line; both empty → "".
    """
    parts = [p.strip() for p in (layer_text, ocr_text) if p and p.strip()]
    return "\n\n".join(parts)


def read_drawing_page(page: "pdfium.PdfPage") -> str:
    """Full text of a drawing page: text layer + OCR of the render."""
    # Imported here — the OCR engine is heavy, not loaded at module import.
    from pdf_processing.ocr import ocr_image

    with PDFIUM_LOCK:
        layer = page.get_textpage().get_text_range().strip()
        width, height = page.get_size()
        scale = RENDER_MAX_SIDE_PX / max(width, height)
        image = page.render(scale=scale).to_pil()
    # OCR outside the lock: it is slow and does not touch pdfium.
    return build_drawing_text(layer, ocr_image(image))


def insert_drawing_pages(document: dict, pdf_path: str, page_types: list[str]) -> None:
    """Insert drawing pages (OCR) into the document at their positions.

    Prose pages were already parsed by Docling and sit in the document.
    Docling never saw the drawing pages — they are read via OCR here and
    the final page list is assembled in the correct order (prose +
    drawings). Prose pages Docling did not produce (blank) are skipped.
    """
    import pypdfium2 as pdfium

    prose_pages = {p["page_number"]: p for p in document["pages"]}
    for page in document["pages"]:
        page["page_type"] = "text"

    with PDFIUM_LOCK:
        doc = pdfium.PdfDocument(pdf_path)
    try:
        pages: list[dict] = []
        for i, page_type in enumerate(page_types):
            page_number = i + 1
            if page_type == "drawing":
                with PDFIUM_LOCK:
                    pdf_page = doc[i]
                drawing_text = read_drawing_page(pdf_page)
                pages.append(
                    {
                        "page_number": page_number,
                        "page_text": drawing_text,
                        "page_type": "drawing",
                        "drawing_text": drawing_text,
                        "blocks": [],
                    }
                )
            elif page_number in prose_pages:
                pages.append(prose_pages[page_number])
        document["pages"] = pages
    finally:
        with PDFIUM_LOCK:
            doc.close()
