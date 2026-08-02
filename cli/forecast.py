"""Processing-cost forecast for a PDF WITHOUT calling the LLM.

Runs Docling parsing locally (free), counts pages and figure/table
blocks, multiplies by the measured averages from common/pricing.py.

Usage:
    python -m cli.forecast path/to/some.pdf   # one file
    python -m cli.forecast path/to/folder/    # every PDF in a folder
"""

import sys
from pathlib import Path

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption

from pdf_processing.parser import build_document_dict, VISUAL_BLOCK_TYPES
from common.pricing import AVG_VISION_COST_PER_IMAGE_PAGE, AVG_EMBEDDING_COST_PER_PAGE


def parse_for_forecast(pdf_path: str) -> dict:
    """Light parse without page screenshots — enough for the page counts."""
    pipeline_options = PdfPipelineOptions()
    pipeline_options.generate_page_images = False

    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
        }
    )

    result = converter.convert(pdf_path)
    return build_document_dict(result.document, Path(pdf_path).name)


def count_pages_and_visuals(document: dict) -> tuple[int, int]:
    """Return (total_pages, pages_with_figure_or_table)."""
    total = len(document["pages"])
    visuals = 0
    for page in document["pages"]:
        has_visual = any(b["type"] in VISUAL_BLOCK_TYPES for b in page["blocks"])
        if has_visual:
            visuals += 1
    return total, visuals


def forecast_one(pdf_path: Path) -> tuple[int, int, float]:
    """Return (total_pages, pages_with_visuals, predicted_usd) for one PDF."""
    document = parse_for_forecast(str(pdf_path))
    total, visuals = count_pages_and_visuals(document)
    cost = (
        visuals * AVG_VISION_COST_PER_IMAGE_PAGE + total * AVG_EMBEDDING_COST_PER_PAGE
    )
    return total, visuals, cost


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python -m cli.forecast <path-to-pdf-or-folder>")
        sys.exit(1)

    if AVG_VISION_COST_PER_IMAGE_PAGE is None or AVG_EMBEDDING_COST_PER_PAGE is None:
        print("[!] Averages missing in pricing.py — run the measurement first.")
        sys.exit(1)

    target = Path(sys.argv[1])
    if not target.exists():
        print(f"[!] Path does not exist: {target}")
        sys.exit(1)

    if target.is_dir():
        forecast_folder(target)
    else:
        forecast_single(target)


def forecast_single(pdf_path: Path) -> None:
    """Forecast for one PDF."""
    total, visuals, cost = forecast_one(pdf_path)
    vision_cost = visuals * AVG_VISION_COST_PER_IMAGE_PAGE
    emb_cost = total * AVG_EMBEDDING_COST_PER_PAGE
    print(f"PDF: {pdf_path.name}")
    print(f"  Pages total:      {total}")
    print(f"  With figure/table: {visuals}")
    print("  Cost forecast:")
    print(f"    vision:         ~${vision_cost:.4f}")
    print(f"    embeddings:     ~${emb_cost:.4f}")
    print(f"    TOTAL:          ~${cost:.4f}")


def forecast_folder(folder: Path) -> None:
    """Combined forecast for every PDF in a folder."""
    pdfs = sorted(folder.glob("*.pdf"))
    if not pdfs:
        print(f"No PDF files found in {folder}.")
        sys.exit(1)

    print(f"PDFs found: {len(pdfs)}\n")

    total_pages_all = 0
    total_visuals_all = 0
    total_cost_all = 0.0
    failures = 0

    for pdf in pdfs:
        print(f"  {pdf.name}: ", end="", flush=True)
        try:
            total, visuals, cost = forecast_one(pdf)
        except Exception as e:
            print(f"[!] error: {e}")
            failures += 1
            continue
        print(f"{total} p., {visuals} with figure/table → ~${cost:.2f}")
        total_pages_all += total
        total_visuals_all += visuals
        total_cost_all += cost

    print("\n=== TOTAL ===")
    print(f"  Processed:       {len(pdfs) - failures} / {len(pdfs)}")
    if failures:
        print(f"  Failures:        {failures}")
    print(f"  Pages total:     {total_pages_all}")
    print(f"  With figure/table: {total_visuals_all}")
    print(f"  Predicted cost:  ~${total_cost_all:.2f}")


if __name__ == "__main__":
    main()
