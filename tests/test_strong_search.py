"""Strong search tests (Step 4): top-source page snapshots for the answering LLM.

They cover the pure pieces: page selection, multimodal message assembly
and rendering a page to base64. The OpenAI call itself is not touched.
"""

import base64

import pypdfium2 as pdfium

from backend.modules.queries.service import collect_page_refs, _render_page_b64
from search.answer import build_user_content


def _chunk(doc: str, pages: list[int], title: str = "Doc") -> dict:
    return {
        "chunk_id": f"{doc}_c001",
        "document_id": doc,
        "document_title": title,
        "pages": pages,
        "text": "text",
    }


def test_collect_page_refs_order_dedup_cap():
    chunks = [
        _chunk("a", [5, 6]),
        _chunk("b", [5]),  # same page of another document — NOT a duplicate
        _chunk("a", [5, 7]),  # (a, 5) already seen — a duplicate
    ]
    assert collect_page_refs(chunks, limit=3) == [("a", 5), ("a", 6), ("b", 5)]


def test_collect_page_refs_respects_limit():
    chunks = [_chunk("a", [1, 2, 3, 4, 5])]
    assert collect_page_refs(chunks, limit=2) == [("a", 1), ("a", 2)]


def test_build_user_content_without_images_is_plain_text():
    content = build_user_content("otázka", [_chunk("a", [1])], page_images=None)
    assert isinstance(content, str)
    assert "otázka" in content


def test_build_user_content_with_images():
    images = [
        {"label": "TZ, s. 4", "b64": "AAAA"},
        {"label": "Výkres, s. 1", "b64": "BBBB"},
    ]
    content = build_user_content("otázka", [_chunk("a", [1])], page_images=images)
    assert isinstance(content, list)
    text_part, *image_parts = content
    assert "1) TZ, s. 4" in text_part["text"]
    assert "2) Výkres, s. 1" in text_part["text"]
    assert len(image_parts) == 2
    assert image_parts[0]["image_url"]["url"].startswith("data:image/png;base64,AAAA")


def test_render_page_b64_real_pdf(tmp_path):
    pdf_path = tmp_path / "one.pdf"
    doc = pdfium.PdfDocument.new()
    doc.new_page(200, 100)
    doc.save(pdf_path)

    b64 = _render_page_b64(pdf_path, 1)

    assert b64 is not None
    png = base64.b64decode(b64)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"  # valid PNG header


def test_render_page_b64_missing_page_returns_none(tmp_path):
    pdf_path = tmp_path / "one.pdf"
    doc = pdfium.PdfDocument.new()
    doc.new_page(200, 100)
    doc.save(pdf_path)

    assert _render_page_b64(pdf_path, 99) is None
