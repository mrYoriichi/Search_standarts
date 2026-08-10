"""Pipeline stage 2: describe schemes and tables via the vision LLM.

Takes document.json (from parse), runs the figure/table pages through
the vision LLM and saves descriptions.json. document.json is NOT
modified — deliberately, so re-running parse never wipes the expensive
vision output.

Run AFTER parse:
    python -m pipeline.parse <pdf>
    python -m pipeline.describe <pdf>
"""

import json
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable

from dotenv import load_dotenv

# Load .env (OpenAI key) BEFORE importing the module that talks to the API.
load_dotenv()

import pypdfium2 as pdfium

from backend.core.paths import CLI_OUTPUT_DIR
from common.jsonio import save_json_atomic
from pdf_processing.drawing import RENDER_MAX_SIDE_PX
from pdf_processing.image_description import (
    VISION_MODEL,
    describe_drawing,
    describe_page_visuals,
    extract_document_metadata,
)

# Лёгкие модули вместо parser: describe работает в ОСНОВНОМ процессе,
# импорт parser затащил бы docling/torch обратно в родителя.
from pdf_processing.document_id import make_document_id
from pdf_processing.visual_blocks import VISUAL_BLOCK_TYPES
from pdf_processing.pdfium_lock import PDFIUM_LOCK
from common.pricing import model_cost

# Сколько vision-запросов одного документа летит параллельно. Это сеть,
# не CPU. Не задирать: до 3 документов идут одновременно (executor в
# app.py), то есть к API уходит до 3 × VISION_CONCURRENCY запросов.
VISION_CONCURRENCY = 4


def load_document(json_path: Path) -> dict:
    """Read document.json into a dict."""
    with open(json_path, encoding="utf-8") as f:
        return json.load(f)


def save_descriptions(descriptions: dict, json_path: Path) -> None:
    """Save the descriptions dict to descriptions.json."""
    save_json_atomic(json_path, descriptions)


def _is_blank(image) -> bool:
    """Uniform (blank) page? Not worth a vision call.

    A blank cover verso used to go to vision as a "drawing" and, thanks
    to the retry in describe_drawing, was paid for TWICE.
    """
    lo, hi = image.convert("L").getextrema()
    return lo == hi


def _render_first_page(pdf_path: str, pages_dir: Path) -> Path | None:
    """Render page 1 from the PDF when Docling did not render it.

    Happens when the first page is a drawing (the router sent it to OCR,
    so there is no p001.png): without this the document would lose its
    title/summary — the typical project-archive case. A render error
    returns None (metadata is skipped, as before).
    """
    try:
        with PDFIUM_LOCK:
            doc = pdfium.PdfDocument(pdf_path)
            try:
                page = doc[0]
                width, height = page.get_size()
                scale = RENDER_MAX_SIDE_PX / max(width, height)
                out = pages_dir / "p001.png"
                page.render(scale=scale).to_pil().save(out)
                return out
            finally:
                doc.close()
    except Exception:
        return None


def _read_partial(json_path: Path) -> dict | None:
    """descriptions.json of a previous (possibly interrupted) run, or None.

    Vision is the most expensive stage, so progress is saved after every
    page and a re-run never re-buys already-paid descriptions.
    """
    try:
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def find_pages_with_visuals(document: dict) -> list[int]:
    """Sorted page numbers that contain figure/table blocks."""
    page_numbers = []
    for page in document["pages"]:
        has_visual = any(
            block["type"] in VISUAL_BLOCK_TYPES for block in page["blocks"]
        )
        if has_visual:
            page_numbers.append(page["page_number"])
    return sorted(page_numbers)


def describe_drawings(
    document: dict,
    pdf_path: str,
    vision_model: str,
    descriptions: dict[str, str],
    on_page_done: Callable[[], None] | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> tuple[int, int]:
    """Vision passports for the document's drawing pages (extends descriptions).

    Drawing pages (page_type == "drawing" from the router) are rendered
    on the fly from the PDF into a temp folder, sent to vision and the
    PNGs discarded — drawing screenshots are never stored.

    descriptions ({page_number: text}) is extended IN PLACE: pages
    already described by a previous run are skipped — they are paid for.
    An empty answer is recorded too ("" = "page processed"; the chunker
    ignores empties). on_page_done fires after each page so the caller
    can persist progress; on_progress(done, total) after each finished
    page feeds the UI.

    Vision calls run VISION_CONCURRENCY at a time (network, not CPU).
    The pool only renders and calls the API; descriptions and callbacks
    are touched by the main thread alone (as_completed loop) — no lock.

    Returns (prompt_tokens, completion_tokens) for this run.
    """
    drawing_pages = [
        p["page_number"] for p in document["pages"] if p.get("page_type") == "drawing"
    ]
    todo = [p for p in drawing_pages if str(p) not in descriptions]
    in_tok = out_tok = 0
    if not todo:
        return in_tok, out_tok

    with PDFIUM_LOCK:
        doc = pdfium.PdfDocument(pdf_path)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)

            def describe_one(page_number: int) -> tuple[int, str, int, int]:
                # Render under the lock; the (long) vision call is outside.
                with PDFIUM_LOCK:
                    page = doc[page_number - 1]
                    width, height = page.get_size()
                    scale = RENDER_MAX_SIDE_PX / max(width, height)
                    pil = page.render(scale=scale).to_pil()
                if _is_blank(pil):
                    # Blank sheet: "" marks it processed; the chunker
                    # ignores empties and a re-run will not come back here.
                    return page_number, "", 0, 0
                tmp_png = tmp_dir / f"draw_{page_number:03d}.png"
                pil.save(tmp_png)
                desc, p_tok, c_tok = describe_drawing(tmp_png, model=vision_model)
                return page_number, desc.strip(), p_tok, c_tok

            with ThreadPoolExecutor(max_workers=VISION_CONCURRENCY) as pool:
                futures = [pool.submit(describe_one, p) for p in todo]
                first_error: BaseException | None = None
                done = 0
                for future in as_completed(futures):
                    try:
                        page_number, desc, p_tok, c_tok = future.result()
                    except BaseException as exc:
                        # Первая ошибка: не начатые запросы отменяем, а уже
                        # летящие дожидаемся и сохраняем — они оплачены.
                        if first_error is None:
                            first_error = exc
                            for f in futures:
                                f.cancel()
                        continue
                    done += 1
                    in_tok += p_tok
                    out_tok += c_tok
                    descriptions[str(page_number)] = desc
                    if on_page_done is not None:
                        on_page_done()
                    if on_progress is not None:
                        on_progress(done, len(todo))
                if first_error is not None:
                    raise first_error
    finally:
        with PDFIUM_LOCK:
            doc.close()
    return in_tok, out_tok


def process(
    pdf_name: str,
    vision_model: str = VISION_MODEL,
    doc_dir: Path | None = None,
    on_progress: Callable[[int, int], None] | None = None,
    pages_dir: Path | None = None,
    pdf_path: str | None = None,
    describe_images: bool = True,
    on_drawing_progress: Callable[[int, int], None] | None = None,
) -> None:
    """Describe schemes and document metadata into descriptions.json.

    pdf_name — the same name passed to parse (e.g. MVL649).
    vision_model — vision LLM id (the cost lever; see the vision_model
    setting).
    doc_dir — document folder; defaults to data/cli_output/<id>, the
    project archive passes its own (projects_data/<slug>).
    on_progress — optional (page_index, total) callback: the backend
    shows UI progress, the CLI lives without it.
    pages_dir — where the page screenshots are; defaults to
    <doc_dir>/pages/ (the .search_index pipeline passes a temp folder).
    pdf_path — path to the source PDF. Set → drawing pages get vision
    passports (rendered on the fly, screenshots never stored). Unset →
    drawings get OCR only.
    describe_images — the "Standard / No LLM" toggle. False → vision is
    never called (no metadata, no scheme or drawing descriptions): an
    empty descriptions.json is written and chunks build from OCR/text —
    free.
    """
    doc_dir = doc_dir or (CLI_OUTPUT_DIR / make_document_id(pdf_name))
    document_path = doc_dir / "document.json"
    descriptions_path = doc_dir / "descriptions.json"
    pages_dir = pages_dir or (doc_dir / "pages")

    # "No LLM" mode: skip vision entirely, leave an empty passport.
    # descriptions.json is still written — chunk.process requires it.
    # BUT a readable existing file is left alone: in a shared folder it
    # may hold a colleague's PAID vision output — never overwrite it
    # with an empty stub.
    if not describe_images:
        print("Image description off (no-LLM mode) — skipping vision.")
        if _read_partial(descriptions_path) is None:
            save_descriptions(
                {
                    "document_title": "",
                    "document_summary": "",
                    "block_descriptions": {},
                    "drawing_descriptions": {},
                },
                descriptions_path,
            )
        return

    document = load_document(document_path)
    pages = find_pages_with_visuals(document)

    print(f"Document: {document['document_name']}")

    # Partial result of a previous (interrupted) run: progress is saved
    # after every page, so paid vision is never re-bought.
    output = _read_partial(descriptions_path) or {
        "document_title": "",
        "document_summary": "",
        "block_descriptions": {},
        "drawing_descriptions": {},
    }
    output.setdefault("described_pages", [])
    done_pages = set(output["described_pages"])

    # Token accumulators: metadata is tracked separately from pages to
    # know the "pure" cost of a figure/table page.
    meta_in = meta_out = 0
    pages_in = pages_out = 0
    pages_described_count = 0

    # Step 1: document title and summary from page 1. If Docling did not
    # render it (first page is a drawing), render it ourselves — the
    # document would otherwise lose its title/summary.
    first_page_image = pages_dir / "p001.png"
    if not first_page_image.exists() and pdf_path:
        first_page_image = _render_first_page(pdf_path, pages_dir) or first_page_image
    if output["document_title"]:
        print("Metadata already present (previous run) — skipping")
    elif first_page_image.exists():
        print("Extracting document metadata...")
        meta, meta_in, meta_out = extract_document_metadata(
            first_page_image, model=vision_model
        )
        output["document_title"] = meta["title"]
        output["document_summary"] = meta["summary"]
        save_descriptions(output, descriptions_path)
        print(f"  Title: {output['document_title']}")
    else:
        print("  [!] No first-page screenshot, metadata skipped")

    # Step 2: describe schemes and tables, accumulating into one dict.
    print(f"\nPages with figure/table: {len(pages)}")
    print("Describing via the vision LLM...\n")

    block_descriptions: dict[str, str] = output["block_descriptions"]
    todo: list[tuple[int, Path]] = []
    for i, page_number in enumerate(pages, start=1):
        if page_number in done_pages:
            print(f"[{i}/{len(pages)}] p. {page_number}: already described, skip")
            continue

        image_path = pages_dir / f"p{page_number:03d}.png"

        if not image_path.exists():
            print(f"[{i}/{len(pages)}] p. {page_number}: no screenshot, skip")
            continue

        todo.append((page_number, image_path))

    # Vision-вызовы летят по VISION_CONCURRENCY параллельно (сеть, не CPU).
    # Пул делает ТОЛЬКО запрос к API; словарь и файл обновляет главный
    # поток в цикле as_completed — потокам нечего делить, замок не нужен.
    # Сохранение после каждой страницы (resume) остаётся как было.
    with ThreadPoolExecutor(max_workers=VISION_CONCURRENCY) as pool:
        futures = {
            pool.submit(
                describe_page_visuals,
                document,
                page_number,
                image_path,
                model=vision_model,
            ): page_number
            for page_number, image_path in todo
        }
        first_error: BaseException | None = None
        done = 0
        for future in as_completed(futures):
            page_number = futures[future]
            try:
                page_descriptions, in_tok, out_tok = future.result()
            except BaseException as exc:
                # Первая ошибка: не начатые запросы отменяем, а уже летящие
                # дожидаемся и сохраняем в descriptions.json — они оплачены.
                if first_error is None:
                    first_error = exc
                    for f in futures:
                        f.cancel()
                continue
            done += 1
            block_descriptions.update(page_descriptions)
            output["described_pages"].append(page_number)
            save_descriptions(output, descriptions_path)
            pages_in += in_tok
            pages_out += out_tok
            pages_described_count += 1
            if on_progress is not None:
                on_progress(done, len(todo))
            print(
                f"[{done}/{len(todo)}] p. {page_number}: "
                f"descriptions set: {len(page_descriptions)}"
            )
        if first_error is not None:
            raise first_error

    # Step 3: vision passports for drawing pages (when the PDF path is
    # known). Progress is saved after every sheet, as above.
    draw_in = draw_out = 0
    if pdf_path:
        print("\nDescribing drawing pages via the vision LLM...")
        draw_in, draw_out = describe_drawings(
            document,
            pdf_path,
            vision_model,
            descriptions=output["drawing_descriptions"],
            on_page_done=lambda: save_descriptions(output, descriptions_path),
            on_progress=on_drawing_progress,
        )
        print(f"  Drawings described: {len(output['drawing_descriptions'])}")
    drawing_descriptions = output["drawing_descriptions"]

    # Final save (covers the case of zero vision calls).
    save_descriptions(output, descriptions_path)

    print("\nDone!")
    print(f"  Descriptions total: {len(block_descriptions)}")
    print(f"  Saved to:           {descriptions_path}")

    meta_usd = model_cost(vision_model, meta_in, meta_out)
    pages_usd = model_cost(vision_model, pages_in, pages_out)
    draw_usd = model_cost(vision_model, draw_in, draw_out)
    total_usd = meta_usd + pages_usd + draw_usd

    print("\n=== Vision cost ===")
    print(
        f"  Metadata:             input={meta_in:>6}, output={meta_out:>5} → ${meta_usd:.4f}"
    )
    print(f"  Pages with figure/table ({pages_described_count}):")
    print(
        f"                        input={pages_in:>6}, output={pages_out:>5} → ${pages_usd:.4f}"
    )
    if pages_described_count:
        per_page_usd = pages_usd / pages_described_count
        print(
            f"  $ per figure/table page:                            ${per_page_usd:.4f}"
        )
    if drawing_descriptions:
        print(f"  Drawings ({len(drawing_descriptions)}):")
        print(
            f"                        input={draw_in:>6}, output={draw_out:>5} → ${draw_usd:.4f}"
        )
    print(f"  TOTAL vision:                                       ${total_usd:.4f}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(
            "Usage:   python -m pipeline.describe <pdf_name> [vision_model] [doc_dir]"
        )
        print("Example: python -m pipeline.describe MVL649 gpt-5.6-sol /tmp/measure_55")
        sys.exit(1)
    # Модель и папку можно задать явно: так один и тот же документ
    # прогоняется на разных моделях в чистые папки — это и есть замер цены.
    process(
        sys.argv[1],
        vision_model=sys.argv[2] if len(sys.argv) > 2 else VISION_MODEL,
        doc_dir=Path(sys.argv[3]) if len(sys.argv) > 3 else None,
    )
