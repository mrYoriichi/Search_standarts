"""Pipeline stage 1: parse a PDF via pdf_processing and save the result.

If storage ever moves to a database, only the save functions change —
the parser stays untouched.
"""

import sys
from pathlib import Path

from backend.core.paths import CLI_OUTPUT_DIR, CLI_PDF_DIR
from common.jsonio import save_json_atomic
from pdf_processing.drawing import insert_drawing_pages
from pdf_processing.page_router import classify_pages
from pdf_processing.parser import (
    collect_pages_to_save,
    enrich_visual_blocks,
    parse_prose_pages,
)


def save_document_json(document: dict, output_root: Path) -> Path:
    """Save the parse result to <output_root>/<document_id>/document.json."""
    doc_dir = output_root / document["document_id"]
    doc_dir.mkdir(parents=True, exist_ok=True)

    output_path = doc_dir / "document.json"
    save_json_atomic(output_path, document)

    return output_path


def save_page_images(
    page_images: dict,
    pages_to_save: set[int],
    pages_dir: Path,
) -> dict[int, str]:
    """Save the selected pages as PNGs into pages_dir.

    Returns {page_number: relative_path} for embedding into the JSON.
    """
    pages_dir.mkdir(parents=True, exist_ok=True)

    saved_paths: dict[int, str] = {}
    for page_num in sorted(pages_to_save):
        image = page_images.get(page_num)
        if image is None:
            continue  # defensive: no image for this page
        filename = f"p{page_num:03d}.png"  # always three digits
        full_path = pages_dir / filename
        image.save(full_path, format="PNG")
        # The JSON stores paths relative to the document folder.
        saved_paths[page_num] = f"pages/{filename}"

    return saved_paths


def process(
    pdf_name: str,
    pdf_path: str | None = None,
    doc_dir: Path | None = None,
    document_id: str | None = None,
    pages_dir: Path | None = None,
    on_text_pages=None,
    on_drawing_page=None,
) -> None:
    """Parse one PDF and save the result.

    pdf_name — file name WITHOUT extension.
    pdf_path — full path to the PDF; defaults to data/pdfs/<pdf_name>.pdf
    (CLI input). The app always passes the path straight from the user's
    folder.
    doc_dir — output folder; defaults to data/cli_output/<document_id>.
    The project archive passes its own pool (projects_data/<slug>).
    document_id — overrides the id derived from the file name. The
    archive passes a {project}__{file} slug — file names repeat between
    projects.
    pages_dir — where page screenshots go; defaults to <doc_dir>/pages/.
    The .search_index pipeline passes a temporary local folder so PNGs
    never travel to a network drive.
    on_text_pages(total) — перед Docling: сколько текстовых страниц
    уйдёт в него одним куском (внутри Docling прогресса нет).
    on_drawing_page(done, total) — после каждой OCR-страницы чертежей.
    """
    if pdf_path is None:
        pdf_path = str(CLI_PDF_DIR / f"{pdf_name}.pdf")

    print(f"Reading {pdf_path}, please wait...")
    # Per-page router: classify every page (prose/drawing). Docling runs
    # ONLY on prose pages (useless and slow on drawings); drawing pages
    # are read by OCR and inserted in their places.
    page_types = classify_pages(pdf_path)
    if on_text_pages:
        on_text_pages(page_types.count("text"))
    document, page_images = parse_prose_pages(pdf_path, page_types)
    if document_id:
        document["document_id"] = document_id
    insert_drawing_pages(document, pdf_path, page_types, on_progress=on_drawing_page)

    doc_dir = doc_dir or (CLI_OUTPUT_DIR / document["document_id"])
    doc_dir.mkdir(parents=True, exist_ok=True)

    # Page 1 is always saved: describe.py reads the document title and
    # summary from it even when it has no visual blocks.
    pages_to_save = collect_pages_to_save(document)
    pages_to_save.add(1)
    pages_dir = pages_dir or (doc_dir / "pages")
    saved_paths = save_page_images(page_images, pages_to_save, pages_dir)

    # Fill in figure/table block fields (image paths, neighbours).
    enrich_visual_blocks(document, pages_to_save)

    output_path = doc_dir / "document.json"
    save_json_atomic(output_path, document)

    total_blocks = sum(len(p["blocks"]) for p in document["pages"])
    print("\nDone!")
    print(f"  File:   {output_path}")
    print(f"  Pages:  {len(document['pages'])}")
    print(f"  Blocks: {total_blocks}")
    print(f"  Page images saved: {len(saved_paths)} (in {pages_dir}/)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:   python -m pipeline.parse <pdf_name>")
        print("Example: python -m pipeline.parse MVL649")
        sys.exit(1)
    process(sys.argv[1])
