"""Tests of the project archive scan: page counts, broken PDF filtering, slugs."""

from pathlib import Path

import pypdfium2 as pdfium
import pytest

from backend.modules.projects.service import count_pages, make_project_slug


def _make_pdf(path: Path, width: float, height: float, pages: int = 1) -> None:
    """Creates an empty PDF with a given page size (in pt)."""
    doc = pdfium.PdfDocument.new()
    for _ in range(pages):
        doc.new_page(width, height)
    doc.save(path)
    doc.close()


def test_count_pages(tmp_path):
    pdf = tmp_path / "tz.pdf"
    _make_pdf(pdf, 595, 842, pages=3)  # A4 portrait
    assert count_pages(pdf) == 3


def test_broken_file_raises(tmp_path):
    fake = tmp_path / "fake.pdf"
    fake.write_text("this is not a pdf")
    with pytest.raises(pdfium.PdfiumError):
        count_pages(fake)


def test_project_slug_format():
    assert make_project_slug("Beta most", "202-200 TZ.pdf") == "beta_most__202_200_tz"


def test_project_slug_includes_subfolder_path():
    # The slug is built from the path inside the project, not just the file
    # name — same-named PDFs in different subfolders must not merge.
    assert (
        make_project_slug("Beta most", "TZ/202-200 TZ.pdf")
        == "beta_most__tz_202_200_tz"
    )
