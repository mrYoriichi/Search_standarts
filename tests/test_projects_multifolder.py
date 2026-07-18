"""Тесты обхода нескольких папок архива проектов."""

from pathlib import Path

import pypdfium2 as pdfium

from backend.modules.projects.service import (
    make_project_slug,
    resolve_project_root,
    scan_archive,
)


def _make_pdf(path: Path, width: float = 595, height: float = 842) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = pdfium.PdfDocument.new()
    doc.new_page(width, height)
    doc.save(path)
    doc.close()


def test_scan_shared_seen_dedups_across_roots(tmp_path):
    # Один и тот же проект+файл в двух папках архива → второй в duplicates.
    a = tmp_path / "A"
    b = tmp_path / "B"
    _make_pdf(a / "Beta_most" / "tz.pdf")
    _make_pdf(b / "Beta_most" / "tz.pdf")

    seen: set[str] = set()
    r1 = scan_archive(a, seen)
    r2 = scan_archive(b, seen)
    assert len(r1.documents) == 1
    assert r2.documents == []
    assert len(r2.duplicates) == 1


def test_scan_distinct_projects_in_two_roots(tmp_path):
    a = tmp_path / "A"
    b = tmp_path / "B"
    _make_pdf(a / "Beta_most" / "tz.pdf")
    _make_pdf(b / "Alfa_most" / "tz.pdf")

    seen: set[str] = set()
    docs = scan_archive(a, seen).documents + scan_archive(b, seen).documents
    slugs = {d.slug for d in docs}
    assert slugs == {
        make_project_slug("Beta_most", "tz.pdf"),
        make_project_slug("Alfa_most", "tz.pdf"),
    }


def test_resolve_project_root_by_file_presence(tmp_path):
    a = tmp_path / "A"
    b = tmp_path / "B"
    _make_pdf(b / "Alfa_most" / "tz.pdf")
    rel = "Alfa_most/tz.pdf"
    assert resolve_project_root([a, b], rel) == b
    assert resolve_project_root([a], rel) is None
