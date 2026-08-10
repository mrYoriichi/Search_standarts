"""PDF parsing into structured JSON via Docling.

The module does NOT know where results are saved — persistence is the
caller's job (the pipeline stages, the web server, ...).
"""

import os
import re
import tempfile
from pathlib import Path

import pypdfium2 as pdfium
from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption

from backend.core.paths import DOCLING_MODELS
from pdf_processing.document_id import make_document_id
from pdf_processing.pdfium_lock import PDFIUM_LOCK


# Docling label → our internal block type. Adding a new type = editing
# this table only.
LABEL_MAP = {
    "text": "text",
    "paragraph": "text",
    "section_header": "heading",
    "title": "heading",
    "page_header": "header",
    "page_footer": "footer",
    "caption": "caption",
    "list_item": "list_item",
    "table": "table",
    "picture": "figure",
    "formula": "formula",
    "code": "code",
    "footnote": "footnote",
}

# Block types whose text contributes to page_text.
TEXT_BLOCK_TYPES = {
    "text",
    "heading",
    "header",
    "footer",
    "caption",
    "list_item",
    "footnote",
}


# Block types that need page screenshots (for the vision LLM).
VISUAL_BLOCK_TYPES = {"figure", "table"}


def map_label(docling_label) -> str:
    """Map a Docling label to our type; unknown labels pass through."""
    label_str = getattr(docling_label, "value", str(docling_label)).lower()
    return LABEL_MAP.get(label_str, label_str)


# Section number at the start of a heading: "7", "7.12", "7.12.5"
SECTION_NUMBER_PATTERN = re.compile(r"^(\d+(?:\.\d+)*)")


def parse_heading_number(text: str) -> tuple[str | None, int | None]:
    """Extract the section number and level from a heading.

    "7  Konstrukční zásady"  -> ("7", 1)
    "7.12  Zábradlí"         -> ("7.12", 2)
    "Seznam zkratek"         -> (None, None)   # unnumbered
    """
    if not text:
        return None, None

    match = SECTION_NUMBER_PATTERN.match(text.strip())
    if not match:
        return None, None

    section_number = match.group(1)
    # Level = dot count + 1: "7" -> level 1.
    level = section_number.count(".") + 1
    return section_number, level


def extract_bbox(item) -> list | None:
    """Block bounding box [x1, y1, x2, y2] as integers, or None."""
    if not item.prov:
        return None
    bbox = item.prov[0].bbox
    return [round(bbox.l), round(bbox.t), round(bbox.r), round(bbox.b)]


def _table_markdown(item, doc) -> str | None:
    """Exact table cell values as markdown text (Docling).

    The vision description of a table is a paraphrase WITHOUT exact
    numbers; searching by values needs the cell text itself. A
    serialization error must not break parsing — the table then simply
    stays without text.
    """
    try:
        markdown = item.export_to_markdown(doc)
    except Exception:
        return None
    return markdown.strip() or None


def make_block(item, block_idx_on_page: int, page_num: int, doc=None) -> dict:
    """Convert one Docling item into our block dict.

    Visual blocks get an extended structure with fields for later stages
    (caption, image_path, description). doc — the DoclingDocument, needed
    by tables to serialize cells to markdown.
    """
    block_type = map_label(item.label)
    block_id = f"p{page_num}_b{block_idx_on_page:02d}"
    bbox = extract_bbox(item)

    if block_type in VISUAL_BLOCK_TYPES:
        block = {
            "block_id": block_id,
            "type": block_type,
            "bbox": bbox,
            "page_image_path": None,
            "prev_page": None,
            "next_page": None,
            "description": None,
        }
        if block_type == "table":
            block["text"] = _table_markdown(item, doc)
        return block

    block = {
        "block_id": block_id,
        "type": block_type,
        "text": getattr(item, "text", None),
        "bbox": bbox,
    }

    # Headings additionally carry the section number and level.
    if block_type == "heading":
        section_number, level = parse_heading_number(block["text"] or "")
        block["section_number"] = section_number
        block["level"] = level

    return block


def build_page_text(blocks: list[dict]) -> str:
    """Concatenate the text of all textual blocks on a page.

    Used as context for the vision LLM when describing adjacent pages.
    """
    pieces = []
    for block in blocks:
        if block["type"] not in TEXT_BLOCK_TYPES:
            continue
        text = block.get("text")
        if text:
            pieces.append(text.strip())
    # Double newlines keep block boundaries visible.
    return "\n\n".join(pieces)


def enrich_visual_blocks(document: dict, pages_to_save: set[int]) -> None:
    """Fill in figure/table block fields (in place):

    - page_image_path — screenshot path (when the page is saved);
    - prev_page/next_page — neighbouring page numbers (None at edges).
    """
    all_page_numbers = {p["page_number"] for p in document["pages"]}

    for page in document["pages"]:
        page_num = page["page_number"]
        for block in page["blocks"]:
            if block["type"] not in VISUAL_BLOCK_TYPES:
                continue

            # Screenshot path is relative to the document folder.
            if page_num in pages_to_save:
                block["page_image_path"] = f"pages/p{page_num:03d}.png"

            prev_num = page_num - 1
            next_num = page_num + 1
            if prev_num in all_page_numbers:
                block["prev_page"] = prev_num
            if next_num in all_page_numbers:
                block["next_page"] = next_num


def build_document_dict(doc, pdf_filename: str) -> dict:
    """Assemble the final document dict in our JSON schema."""
    # Step 1: group blocks by page.
    pages_dict: dict[int, list] = {}
    for item, _level in doc.iterate_items():
        if not item.prov:
            continue
        page_num = item.prov[0].page_no
        if page_num not in pages_dict:
            pages_dict[page_num] = []
        block_idx = len(pages_dict[page_num]) + 1
        pages_dict[page_num].append(make_block(item, block_idx, page_num, doc))

    # Step 2: sorted page list, with page_text built along the way.
    pages_list = [
        {
            "page_number": page_num,
            "page_text": build_page_text(blocks),
            "blocks": blocks,
        }
        for page_num, blocks in sorted(pages_dict.items())
    ]

    return {
        "document_id": make_document_id(pdf_filename),
        "document_name": pdf_filename,
        "pages": pages_list,
    }


def collect_pages_to_save(document: dict) -> set[int]:
    """Page numbers to save as PNGs: only pages containing figure/table.

    The textual context of neighbouring pages travels separately (the
    page_text field) when sent to the vision LLM.
    """
    pages = document["pages"]
    pages_to_save: set[int] = set()

    for page in pages:
        has_visual = any(
            block["type"] in VISUAL_BLOCK_TYPES for block in page["blocks"]
        )
        if not has_visual:
            continue
        pages_to_save.add(page["page_number"])

    return pages_to_save


def parse_pdf(pdf_path: str) -> tuple[dict, dict]:
    """Parse a PDF; returns (document, page_images).

    document — the structured dict; page_images — {page_no: PIL.Image}.
    Saving to disk is the caller's job.
    """
    pipeline_options = PdfPipelineOptions()
    pipeline_options.generate_page_images = True
    pipeline_options.images_scale = 2.0
    # Pre-bundled models (the .exe build) are used when present — docling
    # downloads nothing. Otherwise the default download behaviour applies.
    if DOCLING_MODELS.exists():
        pipeline_options.artifacts_path = str(DOCLING_MODELS)
    # MPS (Apple Silicon GPU) lacks float64 support required by Docling's
    # models (RT-DETR) — force CPU.
    pipeline_options.accelerator_options = AcceleratorOptions(
        device=AcceleratorDevice.CPU
    )

    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
        }
    )

    result = converter.convert(pdf_path)
    doc = result.document

    # Collect page images into a plain dict so Docling objects do not
    # leak into the rest of the code.
    page_images = {}
    for page_num, page in doc.pages.items():
        if page.image and page.image.pil_image:
            page_images[page_num] = page.image.pil_image

    pdf_filename = Path(pdf_path).name
    document = build_document_dict(doc, pdf_filename)

    return document, page_images


def _remap_to_original(
    document: dict, page_images: dict, prose_numbers: list[int], original_name: str
) -> None:
    """Remap temp-PDF page numbers to the original ones (in place).

    Docling numbers the temp PDF 1..M; page j corresponds to
    prose_numbers[j-1]. Fixes page_number, the page part of block_id
    ('p3_b02') and the page_images keys; restores the original id/name.
    """
    document["document_id"] = make_document_id(original_name)
    document["document_name"] = original_name
    mapping = {j + 1: prose_numbers[j] for j in range(len(prose_numbers))}
    for page in document["pages"]:
        new = mapping.get(page["page_number"], page["page_number"])
        page["page_number"] = new
        for block in page["blocks"]:
            block["block_id"] = f"p{new}_" + block["block_id"].split("_", 1)[1]
    remapped = {mapping.get(k, k): v for k, v in page_images.items()}
    page_images.clear()
    page_images.update(remapped)


def parse_prose_pages(pdf_path: str, page_types: list[str]) -> tuple[dict, dict]:
    """Run Docling ONLY over the prose pages (page_types[i] == 'text').

    Docling never sees the drawing pages (useless and slow there). A temp
    PDF is assembled from the prose pages, parsed, and the result comes
    back with the ORIGINAL page numbers.
    """
    original_name = Path(pdf_path).name
    prose_numbers = [i + 1 for i, t in enumerate(page_types) if t == "text"]
    if not prose_numbers:
        # The whole document is drawings — no Docling needed.
        return {
            "document_id": make_document_id(original_name),
            "document_name": original_name,
            "pages": [],
        }, {}

    with PDFIUM_LOCK:
        src = pdfium.PdfDocument(pdf_path)
        dst = pdfium.PdfDocument.new()
        dst.import_pages(src, [n - 1 for n in prose_numbers])
    fd, temp_path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    try:
        with open(temp_path, "wb") as f, PDFIUM_LOCK:
            dst.save(f)
        document, page_images = parse_pdf(temp_path)  # Docling takes the same lock
    finally:
        with PDFIUM_LOCK:
            dst.close()
            src.close()
        os.remove(temp_path)

    _remap_to_original(document, page_images, prose_numbers, original_name)
    return document, page_images
