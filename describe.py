"""
Этап 2: описание схем и таблиц через vision LLM.

Берёт готовый document.json (результат main.py), прогоняет страницы
с figure/table через vision LLM и дописывает описания в тот же файл.

Запускать ПОСЛЕ main.py:
    python main.py       # этап 1: парсинг PDF
    python describe.py   # этап 2: описание схем
"""
import json
from pathlib import Path

from dotenv import load_dotenv

# Загружаем .env (ключ OpenAI) ДО импорта модуля, который обращается к API
load_dotenv()

from pdf_processing.image_description import describe_page_visuals
from pdf_processing.parser import VISUAL_BLOCK_TYPES


def load_document(json_path: Path) -> dict:
    """Читает document.json в словарь."""
    with open(json_path, encoding="utf-8") as f:
        return json.load(f)


def save_document(document: dict, json_path: Path) -> None:
    """Сохраняет словарь обратно в document.json."""
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(document, f, ensure_ascii=False, indent=2)


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


def main():
    # Папка документа. Пока имя задаём вручную — позже сделаем аргументом.
    doc_dir = Path("data/raw_data/mvl649")
    json_path = doc_dir / "document.json"

    document = load_document(json_path)
    pages = find_pages_with_visuals(document)

    print(f"Документ: {document['document_name']}")
    print(f"Страниц с figure/table: {len(pages)}")
    print(f"Начинаю описание через vision LLM...\n")

    total_described = 0
    for i, page_number in enumerate(pages, start=1):
        # Путь к скриншоту этой страницы
        image_path = doc_dir / "pages" / f"p{page_number:03d}.png"

        if not image_path.exists():
            print(f"[{i}/{len(pages)}] стр. {page_number}: скриншота нет, пропуск")
            continue

        print(f"[{i}/{len(pages)}] стр. {page_number}: запрос в LLM...")
        described = describe_page_visuals(document, page_number, image_path)
        total_described += described
        print(f"           проставлено описаний: {described}")

    # Сохраняем обогащённый документ обратно в тот же файл
    save_document(document, json_path)

    print(f"\nГотово!")
    print(f"  Всего описаний проставлено: {total_described}")
    print(f"  Файл обновлён: {json_path}")


if __name__ == "__main__":
    main()