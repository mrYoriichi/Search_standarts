"""
Этап 2: описание схем и таблиц через vision LLM.

Берёт готовый document.json (результат main.py), прогоняет страницы
с figure/table через vision LLM и сохраняет результат в descriptions.json.
document.json НЕ меняется — это сознательно, чтобы перепуск main.py
не стирал дорогие vision-описания.

Запускать ПОСЛЕ main.py:
    python main.py       # этап 1: парсинг PDF
    python describe.py   # этап 2: описание схем
"""

import json
import sys
import tempfile
from pathlib import Path
from typing import Callable

from dotenv import load_dotenv

# Загружаем .env (ключ OpenAI) ДО импорта модуля, который обращается к API
load_dotenv()

import pypdfium2 as pdfium

from backend.core.paths import RAW_DATA_DIR
from jsonio import save_json_atomic
from pdf_processing.drawing import RENDER_MAX_SIDE_PX
from pdf_processing.image_description import (
    VISION_MODEL,
    describe_drawing,
    describe_page_visuals,
    extract_document_metadata,
)
from pdf_processing.parser import VISUAL_BLOCK_TYPES, make_document_id
from pricing import model_cost


def load_document(json_path: Path) -> dict:
    """Читает document.json в словарь."""
    with open(json_path, encoding="utf-8") as f:
        return json.load(f)


def save_descriptions(descriptions: dict, json_path: Path) -> None:
    """Сохраняет словарь описаний в descriptions.json."""
    save_json_atomic(json_path, descriptions)


def _read_partial(json_path: Path) -> dict | None:
    """descriptions.json прошлого (возможно, оборванного) запуска или None.

    Vision — самый дорогой этап, поэтому сохраняемся после каждой страницы,
    а при повторном запуске уже оплаченные описания не покупаем второй раз.
    """
    try:
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def find_pages_with_visuals(document: dict) -> list[int]:
    """
    Возвращает отсортированный список номеров страниц,
    на которых есть блоки figure/table.
    """
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
) -> tuple[int, int]:
    """Vision-описание чертёжных страниц документа (дополняет descriptions).

    Чертёжные страницы (по-страничный роутер пометил их page_type == "drawing")
    рендерим на лету из PDF во временную папку, отдаём в vision и выбрасываем
    PNG — скриншоты чертежей нигде не храним.

    descriptions ({номер_страницы: текст}) пополняется НА МЕСТЕ: страницы, уже
    описанные прошлым запуском, пропускаем — за них заплачено. Пустой ответ
    тоже записываем ("" = «страница обработана», chunker пустые игнорирует).
    on_page_done зовётся после каждой страницы — вызывающий сохраняет прогресс.
    Возвращает (prompt_tokens, completion_tokens) этого запуска.
    """
    drawing_pages = [
        p["page_number"] for p in document["pages"] if p.get("page_type") == "drawing"
    ]
    todo = [p for p in drawing_pages if str(p) not in descriptions]
    in_tok = out_tok = 0
    if not todo:
        return in_tok, out_tok

    doc = pdfium.PdfDocument(pdf_path)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            for page_number in todo:
                page = doc[page_number - 1]
                width, height = page.get_size()
                scale = RENDER_MAX_SIDE_PX / max(width, height)
                tmp_png = tmp_dir / f"draw_{page_number:03d}.png"
                page.render(scale=scale).to_pil().save(tmp_png)
                desc, p_tok, c_tok = describe_drawing(tmp_png, model=vision_model)
                in_tok += p_tok
                out_tok += c_tok
                descriptions[str(page_number)] = desc.strip()
                if on_page_done is not None:
                    on_page_done()
    finally:
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
) -> None:
    """
    Описывает схемы и метаданные документа, результат пишет в descriptions.json.
    pdf_name — то же имя, что передавалось в main.py (например, MVL649).
    vision_model — модель vision LLM (рычаг стоимости; см. настройку vision_model).
    doc_dir — папка документа; по умолчанию data/raw_data/<id> (нормы),
    архив проектов передаёт свою (projects_data/<slug>).
    on_progress — необязательный колбэк (номер страницы по счёту, всего страниц):
    бэкенд показывает прогресс в UI, CLI живёт без него.
    pages_dir — где лежат скриншоты страниц; по умолчанию <doc_dir>/pages/
    (пайплайн .search_index передаёт временную локальную папку).
    pdf_path — путь к исходному PDF. Задан → чертёжные страницы получают
    vision-описание (рендер на лету из PDF, скриншоты не храним). Не задан →
    чертежи только с OCR.
    describe_images — тумблер «Стандарт/Без LLM». False → vision не вызывается
    вовсе (ни метаданные, ни схемы прозы, ни чертежи): пишем пустой
    descriptions.json, чанки соберутся из OCR/текста — бесплатно.
    """
    doc_dir = doc_dir or (RAW_DATA_DIR / make_document_id(pdf_name))
    document_path = doc_dir / "document.json"
    descriptions_path = doc_dir / "descriptions.json"
    pages_dir = pages_dir or (doc_dir / "pages")

    # Режим «Без LLM»: vision пропускаем целиком, оставляем пустой паспорт.
    # descriptions.json всё равно пишем — chunk.process без него не запустится.
    if not describe_images:
        print("Popis obrázků vypnut (režim bez LLM) — vision se přeskakuje.")
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

    print(f"Документ: {document['document_name']}")

    # Частичный результат прошлого (оборванного) запуска: сохраняемся после
    # каждой страницы, при повторе уже оплаченное vision не покупаем заново.
    output = _read_partial(descriptions_path) or {
        "document_title": "",
        "document_summary": "",
        "block_descriptions": {},
        "drawing_descriptions": {},
    }
    output.setdefault("described_pages", [])
    done_pages = set(output["described_pages"])

    # Накопители токенов: метаданные считаем отдельно от страниц,
    # чтобы знать "чистую" цену страницы с figure/table.
    meta_in = meta_out = 0
    pages_in = pages_out = 0
    pages_described_count = 0

    # Шаг 1: извлекаем название и описание документа по первой странице
    first_page_image = pages_dir / "p001.png"
    if output["document_title"]:
        print("Метаданные уже есть (прошлый запуск) — пропускаю")
    elif first_page_image.exists():
        print("Извлекаю метаданные документа...")
        meta, meta_in, meta_out = extract_document_metadata(
            first_page_image, model=vision_model
        )
        output["document_title"] = meta["title"]
        output["document_summary"] = meta["summary"]
        save_descriptions(output, descriptions_path)
        print(f"  Название: {output['document_title']}")
    else:
        print("  [!] Скриншота первой страницы нет, метаданные пропущены")

    # Шаг 2: описываем схемы и таблицы — накапливаем в общий словарь
    print(f"\nСтраниц с figure/table: {len(pages)}")
    print("Начинаю описание через vision LLM...\n")

    block_descriptions: dict[str, str] = output["block_descriptions"]
    for i, page_number in enumerate(pages, start=1):
        if page_number in done_pages:
            print(f"[{i}/{len(pages)}] стр. {page_number}: уже описана, пропуск")
            continue

        # Путь к скриншоту этой страницы
        image_path = pages_dir / f"p{page_number:03d}.png"

        if not image_path.exists():
            print(f"[{i}/{len(pages)}] стр. {page_number}: скриншота нет, пропуск")
            continue

        if on_progress is not None:
            on_progress(i, len(pages))
        print(f"[{i}/{len(pages)}] стр. {page_number}: запрос в LLM...")
        page_descriptions, in_tok, out_tok = describe_page_visuals(
            document, page_number, image_path, model=vision_model
        )
        block_descriptions.update(page_descriptions)
        output["described_pages"].append(page_number)
        save_descriptions(output, descriptions_path)
        pages_in += in_tok
        pages_out += out_tok
        pages_described_count += 1
        print(f"           проставлено описаний: {len(page_descriptions)}")

    # Шаг 3: vision-описание чертёжных страниц (если дан путь к PDF).
    # Рендерим их на лету из PDF, скриншоты не сохраняем. Прогресс сохраняем
    # после каждого листа (on_page_done) — как и для страниц выше.
    draw_in = draw_out = 0
    if pdf_path:
        print("\nОписываю чертёжные страницы через vision LLM...")
        draw_in, draw_out = describe_drawings(
            document,
            pdf_path,
            vision_model,
            descriptions=output["drawing_descriptions"],
            on_page_done=lambda: save_descriptions(output, descriptions_path),
        )
        print(f"  Описано чертежей: {len(output['drawing_descriptions'])}")
    drawing_descriptions = output["drawing_descriptions"]

    # Финальное сохранение (на случай, когда ни одного vision-вызова не было)
    save_descriptions(output, descriptions_path)

    print("\nГотово!")
    print(f"  Всего описаний проставлено: {len(block_descriptions)}")
    print(f"  Файл сохранён:              {descriptions_path}")

    # ---- Сводка по стоимости ----
    meta_usd = model_cost(vision_model, meta_in, meta_out)
    pages_usd = model_cost(vision_model, pages_in, pages_out)
    draw_usd = model_cost(vision_model, draw_in, draw_out)
    total_usd = meta_usd + pages_usd + draw_usd

    print("\n=== Стоимость vision ===")
    print(
        f"  Метаданные:           input={meta_in:>6}, output={meta_out:>5} → ${meta_usd:.4f}"
    )
    print(f"  Страницы с figure/table ({pages_described_count} шт.):")
    print(
        f"                        input={pages_in:>6}, output={pages_out:>5} → ${pages_usd:.4f}"
    )
    if pages_described_count:
        per_page_usd = pages_usd / pages_described_count
        print(
            f"  $ на страницу с figure/table:                       ${per_page_usd:.4f}"
        )
    if drawing_descriptions:
        print(f"  Чертежи ({len(drawing_descriptions)} шт.):")
        print(
            f"                        input={draw_in:>6}, output={draw_out:>5} → ${draw_usd:.4f}"
        )
    print(f"  ИТОГО vision:                                       ${total_usd:.4f}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Использование: python describe.py <pdf_name>")
        print("Пример:        python describe.py MVL649")
        sys.exit(1)
    process(sys.argv[1])
