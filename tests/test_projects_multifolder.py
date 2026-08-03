"""Tests of walking project folders: each connected folder = one project."""

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


def test_scan_whole_folder_is_one_project(tmp_path):
    # PDFs in the root and in subfolders — all one project named after the folder.
    root = tmp_path / "Beta_most"
    _make_pdf(root / "tz.pdf")
    _make_pdf(root / "vykresy" / "202_404.pdf")

    result = scan_archive(root, set())
    assert len(result.documents) == 2
    assert {d.project for d in result.documents} == {"Beta_most"}


def test_scan_same_filename_in_subfolders_both_indexed(tmp_path):
    # Same-named PDFs in different project subfolders are different
    # documents, because the slug includes the path, not just the file name.
    root = tmp_path / "Beta_most"
    _make_pdf(root / "TZ" / "plan.pdf")
    _make_pdf(root / "vykresy" / "plan.pdf")

    result = scan_archive(root, set())
    assert len(result.documents) == 2
    assert result.duplicates == []


def test_scan_shared_seen_dedups_across_roots(tmp_path):
    # Two same-named connected folders with the same file -> the second goes to duplicates.
    a = tmp_path / "A" / "Beta_most"
    b = tmp_path / "B" / "Beta_most"
    _make_pdf(a / "tz.pdf")
    _make_pdf(b / "tz.pdf")

    seen: set[str] = set()
    r1 = scan_archive(a, seen)
    r2 = scan_archive(b, seen)
    assert len(r1.documents) == 1
    assert r2.documents == []
    assert len(r2.duplicates) == 1


def test_scan_distinct_projects_in_two_roots(tmp_path):
    a = tmp_path / "Beta_most"
    b = tmp_path / "Alfa_most"
    _make_pdf(a / "tz.pdf")
    _make_pdf(b / "tz.pdf")

    seen: set[str] = set()
    docs = scan_archive(a, seen).documents + scan_archive(b, seen).documents
    slugs = {d.slug for d in docs}
    assert slugs == {
        make_project_slug("Beta_most", "tz.pdf"),
        make_project_slug("Alfa_most", "tz.pdf"),
    }


def test_resolve_project_root_by_name_and_file(tmp_path):
    # Both projects contain TZ/tz.pdf — the folder of the RIGHT project must
    # be returned, or the pipeline processes someone else's file.
    a = tmp_path / "Beta_most"
    b = tmp_path / "Alfa_most"
    _make_pdf(a / "TZ" / "tz.pdf")
    _make_pdf(b / "TZ" / "tz.pdf")
    rel = "TZ/tz.pdf"

    assert resolve_project_root([a, b], "Beta_most", rel) == a
    assert resolve_project_root([a, b], "Alfa_most", rel) == b
    assert resolve_project_root([a], "Alfa_most", rel) is None
