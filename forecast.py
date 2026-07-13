"""
Прогноз стоимости обработки PDF БЕЗ обращения к LLM.

Запускает Docling-парсинг (локально, бесплатно), считает страницы и блоки
figure/table, умножает на средние цены из pricing.py (заполнены после
реального замера на MVL649 и TP_107).

Использование:
    python forecast.py path/to/some.pdf      # прогноз для одного файла
    python forecast.py path/to/folder/       # суммарный прогноз по всем PDF в папке
"""
import sys
from pathlib import Path

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption

from pdf_processing.parser import build_document_dict, VISUAL_BLOCK_TYPES
from pricing import AVG_VISION_COST_PER_IMAGE_PAGE, AVG_EMBEDDING_COST_PER_PAGE


def parse_for_forecast(pdf_path: str) -> dict:
    """
    Лёгкий парсинг PDF: без генерации скриншотов страниц.
    Достаточно для подсчёта числа страниц и страниц с figure/table.
    """
    pipeline_options = PdfPipelineOptions()
    # Для прогноза скриншоты не нужны — экономим время на больших папках.
    pipeline_options.generate_page_images = False

    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
        }
    )

    result = converter.convert(pdf_path)
    return build_document_dict(result.document, Path(pdf_path).name)


def count_pages_and_visuals(document: dict) -> tuple[int, int]:
    """Возвращает (total_pages, pages_with_figure_or_table)."""
    total = len(document["pages"])
    visuals = 0
    for page in document["pages"]:
        has_visual = any(b["type"] in VISUAL_BLOCK_TYPES for b in page["blocks"])
        if has_visual:
            visuals += 1
    return total, visuals


def forecast_one(pdf_path: Path) -> tuple[int, int, float]:
    """Возвращает (total_pages, pages_with_visuals, predicted_usd) для одного PDF."""
    document = parse_for_forecast(str(pdf_path))
    total, visuals = count_pages_and_visuals(document)
    cost = (
        visuals * AVG_VISION_COST_PER_IMAGE_PAGE
        + total * AVG_EMBEDDING_COST_PER_PAGE
    )
    return total, visuals, cost


def main() -> None:
    if len(sys.argv) < 2:
        print("Использование: python forecast.py <path-to-pdf-or-folder>")
        sys.exit(1)

    if AVG_VISION_COST_PER_IMAGE_PAGE is None or AVG_EMBEDDING_COST_PER_PAGE is None:
        print("[!] В pricing.py не заданы средние цены. Сначала запусти замер.")
        sys.exit(1)

    target = Path(sys.argv[1])
    if not target.exists():
        print(f"[!] Путь не существует: {target}")
        sys.exit(1)

    if target.is_dir():
        forecast_folder(target)
    else:
        forecast_single(target)


def forecast_single(pdf_path: Path) -> None:
    """Прогноз для одного PDF."""
    total, visuals, cost = forecast_one(pdf_path)
    vision_cost = visuals * AVG_VISION_COST_PER_IMAGE_PAGE
    emb_cost = total * AVG_EMBEDDING_COST_PER_PAGE
    print(f"PDF: {pdf_path.name}")
    print(f"  Страниц всего:    {total}")
    print(f"  С figure/table:   {visuals}")
    print("  Прогноз стоимости:")
    print(f"    vision:         ~${vision_cost:.4f}")
    print(f"    embeddings:     ~${emb_cost:.4f}")
    print(f"    ИТОГО:          ~${cost:.4f}")


def forecast_folder(folder: Path) -> None:
    """Суммарный прогноз по всем PDF в папке."""
    pdfs = sorted(folder.glob("*.pdf"))
    if not pdfs:
        print(f"В {folder} не найдено PDF-файлов.")
        sys.exit(1)

    print(f"Найдено PDF: {len(pdfs)}\n")

    total_pages_all = 0
    total_visuals_all = 0
    total_cost_all = 0.0
    failures = 0

    for pdf in pdfs:
        print(f"  {pdf.name}: ", end="", flush=True)
        try:
            total, visuals, cost = forecast_one(pdf)
        except Exception as e:
            print(f"[!] ошибка: {e}")
            failures += 1
            continue
        print(f"{total} стр., {visuals} с figure/table → ~${cost:.2f}")
        total_pages_all += total
        total_visuals_all += visuals
        total_cost_all += cost

    print("\n=== ИТОГ ===")
    print(f"  Обработано:               {len(pdfs) - failures} / {len(pdfs)}")
    if failures:
        print(f"  Ошибок:                   {failures}")
    print(f"  Всего страниц:            {total_pages_all}")
    print(f"  С figure/table:           {total_visuals_all}")
    print(f"  Прогнозируемая стоимость: ~${total_cost_all:.2f}")


if __name__ == "__main__":
    main()
