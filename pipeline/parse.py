"""Pipeline stage 1: parse a PDF via pdf_processing and save the result.

If storage ever moves to a database, only the save functions change —
the parser stays untouched.

Resume: when the artifacts already hold an intact document.json (atomic
writes guarantee integrity) and the PDF has not changed since, Docling/
OCR are skipped entirely — only the page screenshots are re-rendered
via pdfium. A describe crash on page 200 of 769 then costs minutes, not
an hour of re-parsing. The heavy ML imports live inside _full_parse so
the resume path never loads them.
"""

import json
import os
import sys
from pathlib import Path

import pypdfium2 as pdfium

from backend.core.paths import CLI_OUTPUT_DIR, CLI_PDF_DIR
from common.jsonio import save_json_atomic
from pdf_processing.pdfium_lock import PDFIUM_LOCK
from pdf_processing.visual_blocks import collect_pages_to_save

# Масштаб рендера скриншотов. Должен совпадать с images_scale в
# parser.parse_pdf (докling-рендер), иначе резюм даст vision картинки
# другого размера.
IMAGE_SCALE = 2.0


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


def _source_stat(pdf_path: str) -> dict:
    """Отпечаток исходного PDF для document.json (размер + mtime)."""
    st = os.stat(pdf_path)
    return {"file_size": st.st_size, "file_mtime": st.st_mtime}


def _load_resumable(pdf_path: str, doc_dir: Path, document_id: str) -> dict | None:
    """document.json из артефактов, если парс можно не повторять.

    Условия: файл читается (atomic-запись гарантирует целостность),
    document_id совпадает и PDF не менялся с момента парсинга (отпечаток
    source). Иначе None — нужен полный парс.
    """
    try:
        document = json.loads((doc_dir / "document.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(document, dict) or document.get("document_id") != document_id:
        return None
    source = document.get("source")
    try:
        if source != _source_stat(pdf_path):
            return None
    except OSError:
        # PDF не читается — пусть полный парс упадёт привычной ошибкой.
        return None
    return document


def _render_pages(pdf_path: str, pages_to_save: set[int], pages_dir: Path) -> int:
    """Пере-рендер скриншотов страниц через pdfium (без Docling).

    Тот же масштаб и имена файлов, что у полного парса. Возвращает
    число сохранённых страниц.
    """
    pages_dir.mkdir(parents=True, exist_ok=True)
    with PDFIUM_LOCK:
        doc = pdfium.PdfDocument(pdf_path)
    try:
        saved = 0
        for page_num in sorted(pages_to_save):
            if page_num > len(doc):
                continue  # defensive: страницы нет в PDF
            with PDFIUM_LOCK:
                image = doc[page_num - 1].render(scale=IMAGE_SCALE).to_pil()
            image.save(pages_dir / f"p{page_num:03d}.png", format="PNG")
            saved += 1
        return saved
    finally:
        with PDFIUM_LOCK:
            doc.close()


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

    # Резюм — только путь приложения (doc_dir + document_id заданы);
    # CLI-запуск всегда парсит заново.
    if doc_dir is not None and document_id is not None:
        document = _load_resumable(pdf_path, doc_dir, document_id)
        if document is not None:
            pages_to_save = collect_pages_to_save(document)
            pages_to_save.add(1)
            pages_dir = pages_dir or (doc_dir / "pages")
            saved = _render_pages(pdf_path, pages_to_save, pages_dir)
            print(
                f"Resume: intact document.json, PDF unchanged — "
                f"skipped Docling/OCR, re-rendered {saved} page screenshots"
            )
            return

    _full_parse(
        pdf_path, doc_dir, document_id, pages_dir, on_text_pages, on_drawing_page
    )


def _full_parse(
    pdf_path: str,
    doc_dir: Path | None,
    document_id: str | None,
    pages_dir: Path | None,
    on_text_pages,
    on_drawing_page,
) -> None:
    """Полный парс: Docling по прозе + OCR по чертежам (см. process)."""
    # Ленивые импорты: docling/torch грузятся только здесь — путь резюма
    # (и сам старт воркера) остаётся лёгким.
    from pdf_processing.drawing import insert_drawing_pages
    from pdf_processing.page_router import classify_pages
    from pdf_processing.parser import enrich_visual_blocks, parse_prose_pages

    # Отпечаток PDF снимаем ДО чтения: если файл подменят во время
    # часового парса, резюм со свежим stat не совпадёт и перепарсит.
    try:
        source = _source_stat(pdf_path)
    except OSError:
        source = None  # файла нет — парс ниже упадёт привычной ошибкой

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
    if source is not None:
        document["source"] = source

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
