"""Прогресс парсинга по страницам: чтобы UI не выглядел зависшим.

OCR чертёжных страниц — самая долгая часть парсинга сканированных
документов; insert_drawing_pages должен сообщать «страница X из N»
через колбэк (сам рендер/OCR в тесте подменён).
"""

import pypdfium2 as pdfium

from pdf_processing import drawing


def _make_pdf(tmp_path, n_pages: int) -> str:
    doc = pdfium.PdfDocument.new()
    for _ in range(n_pages):
        doc.new_page(200, 200)
    pdf_path = tmp_path / "test.pdf"
    doc.save(pdf_path)
    doc.close()
    return str(pdf_path)


def test_drawing_pages_report_progress(tmp_path, monkeypatch):
    monkeypatch.setattr(drawing, "read_drawing_page", lambda page: "text")
    pdf_path = _make_pdf(tmp_path, 3)
    document = {"pages": []}
    calls: list[tuple[int, int]] = []

    drawing.insert_drawing_pages(
        document,
        pdf_path,
        ["drawing", "text", "drawing"],
        on_progress=lambda done, total: calls.append((done, total)),
    )

    # 2 чертёжные страницы из 3: колбэк по одному разу на каждую.
    assert calls == [(1, 2), (2, 2)]


def test_no_callback_still_works(tmp_path, monkeypatch):
    monkeypatch.setattr(drawing, "read_drawing_page", lambda page: "text")
    pdf_path = _make_pdf(tmp_path, 1)
    document = {"pages": []}

    drawing.insert_drawing_pages(document, pdf_path, ["drawing"])

    assert document["pages"][0]["page_type"] == "drawing"
