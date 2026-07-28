"""Тесты скана архива проектов: подсчёт страниц, отсев битых PDF, slug."""

from pathlib import Path

import pypdfium2 as pdfium
import pytest

from backend.modules.projects.service import count_pages, make_project_slug


def _make_pdf(path: Path, width: float, height: float, pages: int = 1) -> None:
    """Создаёт пустой PDF с заданным размером страниц (в pt)."""
    doc = pdfium.PdfDocument.new()
    for _ in range(pages):
        doc.new_page(width, height)
    doc.save(path)
    doc.close()


def test_count_pages(tmp_path):
    pdf = tmp_path / "tz.pdf"
    _make_pdf(pdf, 595, 842, pages=3)  # A4 портрет
    assert count_pages(pdf) == 3


def test_broken_file_raises(tmp_path):
    fake = tmp_path / "fake.pdf"
    fake.write_text("this is not a pdf")
    with pytest.raises(pdfium.PdfiumError):
        count_pages(fake)


def test_project_slug_format():
    assert make_project_slug("Beta most", "202-200 TZ.pdf") == "beta_most__202_200_tz"


def test_project_slug_includes_subfolder_path():
    # Slug строится из пути внутри проекта, не только из имени файла —
    # одноимённые PDF в разных подпапках не должны склеиваться.
    assert make_project_slug("Beta most", "TZ/202-200 TZ.pdf") == "beta_most__tz_202_200_tz"
