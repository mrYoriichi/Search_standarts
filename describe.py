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
from pathlib import Path

from dotenv import load_dotenv

# Загружаем .env (ключ OpenAI) ДО импорта модуля, который обращается к API
load_dotenv()

from backend.core.paths import RAW_DATA_DIR
from pdf_processing.image_description import (
    VISION_MODEL,
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
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(descriptions, f, ensure_ascii=False, indent=2)


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


def process(
    pdf_name: str,
    vision_model: str = VISION_MODEL,
    doc_dir: Path | None = None,
) -> None:
    """
    Описывает схемы и метаданные документа, результат пишет в descriptions.json.
    pdf_name — то же имя, что передавалось в main.py (например, MVL649).
    vision_model — модель vision LLM (рычаг стоимости; см. настройку vision_model).
    doc_dir — папка документа; по умолчанию data/raw_data/<id> (нормы),
    архив проектов передаёт свою (projects_data/<slug>).
    """
    doc_dir = doc_dir or (RAW_DATA_DIR / make_document_id(pdf_name))
    document_path = doc_dir / "document.json"
    descriptions_path = doc_dir / "descriptions.json"

    document = load_document(document_path)
    pages = find_pages_with_visuals(document)

    print(f"Документ: {document['document_name']}")

    # Накопители токенов: метаданные считаем отдельно от страниц,
    # чтобы знать "чистую" цену страницы с figure/table.
    meta_in = meta_out = 0
    pages_in = pages_out = 0
    pages_described_count = 0

    # Шаг 1: извлекаем название и описание документа по первой странице
    first_page_image = doc_dir / "pages" / "p001.png"
    if first_page_image.exists():
        print("Извлекаю метаданные документа...")
        meta, meta_in, meta_out = extract_document_metadata(
            first_page_image, model=vision_model
        )
        document_title = meta["title"]
        document_summary = meta["summary"]
        print(f"  Название: {document_title}")
    else:
        print("  [!] Скриншота первой страницы нет, метаданные пропущены")
        document_title = ""
        document_summary = ""

    # Шаг 2: описываем схемы и таблицы — накапливаем в общий словарь
    print(f"\nСтраниц с figure/table: {len(pages)}")
    print(f"Начинаю описание через vision LLM...\n")

    block_descriptions: dict[str, str] = {}
    for i, page_number in enumerate(pages, start=1):
        # Путь к скриншоту этой страницы
        image_path = doc_dir / "pages" / f"p{page_number:03d}.png"

        if not image_path.exists():
            print(f"[{i}/{len(pages)}] стр. {page_number}: скриншота нет, пропуск")
            continue

        print(f"[{i}/{len(pages)}] стр. {page_number}: запрос в LLM...")
        page_descriptions, in_tok, out_tok = describe_page_visuals(
            document, page_number, image_path, model=vision_model
        )
        block_descriptions.update(page_descriptions)
        pages_in += in_tok
        pages_out += out_tok
        pages_described_count += 1
        print(f"           проставлено описаний: {len(page_descriptions)}")

    # Сохраняем результат в descriptions.json (полная перезапись)
    output = {
        "document_title": document_title,
        "document_summary": document_summary,
        "block_descriptions": block_descriptions,
    }
    save_descriptions(output, descriptions_path)

    print(f"\nГотово!")
    print(f"  Всего описаний проставлено: {len(block_descriptions)}")
    print(f"  Файл сохранён:              {descriptions_path}")

    # ---- Сводка по стоимости ----
    meta_usd = model_cost(vision_model, meta_in, meta_out)
    pages_usd = model_cost(vision_model, pages_in, pages_out)
    total_usd = meta_usd + pages_usd

    print(f"\n=== Стоимость vision ===")
    print(f"  Метаданные:           input={meta_in:>6}, output={meta_out:>5} → ${meta_usd:.4f}")
    print(f"  Страницы с figure/table ({pages_described_count} шт.):")
    print(f"                        input={pages_in:>6}, output={pages_out:>5} → ${pages_usd:.4f}")
    if pages_described_count:
        per_page_usd = pages_usd / pages_described_count
        print(f"  $ на страницу с figure/table:                       ${per_page_usd:.4f}")
    print(f"  ИТОГО vision:                                       ${total_usd:.4f}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Использование: python describe.py <pdf_name>")
        print("Пример:        python describe.py MVL649")
        sys.exit(1)
    process(sys.argv[1])
