"""Тесты классификации PDF архива проектов (sheet/text по размеру страницы)."""

from pathlib import Path

import pypdfium2 as pdfium
import pytest

from backend.modules.projects.service import classify_pdf, make_project_slug


def _make_pdf(path: Path, width: float, height: float, pages: int = 1) -> None:
    """Создаёт пустой PDF с заданным размером страниц (в pt)."""
    doc = pdfium.PdfDocument.new()
    for _ in range(pages):
        doc.new_page(width, height)
    doc.save(path)
    doc.close()


def test_a4_is_text(tmp_path):
    pdf = tmp_path / "tz.pdf"
    _make_pdf(pdf, 595, 842, pages=3)  # A4 портрет
    assert classify_pdf(pdf) == ("text", 3)


def test_a1_landscape_is_sheet(tmp_path):
    pdf = tmp_path / "vykres.pdf"
    _make_pdf(pdf, 2384, 1684)  # A1 альбомный
    assert classify_pdf(pdf) == ("sheet", 1)


def test_a3_is_still_text(tmp_path):
    # Граница: длинная сторона A3 = 1191 pt < порога 1250 -> ещё текст.
    # Ловит случайное изменение порога _SHEET_LONG_SIDE_PT.
    pdf = tmp_path / "priloha.pdf"
    _make_pdf(pdf, 842, 1191)
    assert classify_pdf(pdf) == ("text", 1)


def test_broken_file_raises(tmp_path):
    fake = tmp_path / "fake.pdf"
    fake.write_text("this is not a pdf")
    with pytest.raises(pdfium.PdfiumError):
        classify_pdf(fake)


def test_project_slug_format():
    assert make_project_slug("Beta most", "202-200 TZ.pdf") == "beta_most__202_200_tz"
