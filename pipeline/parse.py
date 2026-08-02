"""
Точка входа в проект.
Разбирает PDF через pdf_processing.parser и сохраняет результат на диск.
Когда переедем на БД, изменится только функция сохранения — парсер не трогаем.
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
    """
    Сохраняет результат разбора в data/cli_output/<document_id>/document.json.
    Возвращает путь к созданному файлу.
    """
    # У каждого документа своя папка с именем = document_id
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
    """
    Сохраняет указанные страницы как PNG в pages_dir.
    Возвращает словарь {номер_страницы: относительный_путь} —
    он пригодится, чтобы вписать пути в JSON.

    page_images   — все картинки страниц из парсера (PIL.Image).
    pages_to_save — какие именно страницы реально сохраняем.
    pages_dir     — куда класть PNG (по умолчанию <doc_dir>/pages/).
    """
    pages_dir.mkdir(parents=True, exist_ok=True)

    saved_paths: dict[int, str] = {}
    for page_num in sorted(pages_to_save):
        image = page_images.get(page_num)
        if image is None:
            # Подстраховка: вдруг для этой страницы картинки нет
            continue
        # Имя файла: p001.png, p012.png — всегда три цифры
        filename = f"p{page_num:03d}.png"
        full_path = pages_dir / filename
        image.save(full_path, format="PNG")
        # В JSON будет лежать относительный путь от папки документа
        saved_paths[page_num] = f"pages/{filename}"

    return saved_paths


def process(
    pdf_name: str,
    pdf_path: str | None = None,
    doc_dir: Path | None = None,
    document_id: str | None = None,
    pages_dir: Path | None = None,
) -> None:
    """
    Разбирает один PDF и сохраняет результат в data/cli_output/<document_id>/.
    pdf_name — имя файла БЕЗ расширения.
    pdf_path — полный путь к PDF. Если не задан, берётся data/pdfs/<pdf_name>.pdf
    (вход CLI-сценария). Приложение всегда передаёт путь к PDF прямо из папки
    юзера.
    doc_dir — папка результатов. Если не задана — data/cli_output/<document_id>
    (нормы). Архив проектов передаёт свой пул (projects_data/<slug>).
    document_id — переопределяет id из имени файла. Архив проектов передаёт
    slug вида {проект}__{файл} — имена файлов между проектами повторяются.
    pages_dir — куда класть скриншоты страниц. По умолчанию <doc_dir>/pages/;
    пайплайн .search_index передаёт временную локальную папку, чтобы PNG
    не ехали на сетевой диск.
    """
    if pdf_path is None:
        pdf_path = str(CLI_PDF_DIR / f"{pdf_name}.pdf")

    print(f"Читаю {pdf_path}, подожди...")
    # По-страничный роутер: классифицируем каждую страницу (проза/чертёж),
    # Docling запускаем ТОЛЬКО по прозаическим (на чертежах он бесполезен и
    # тормозит), чертёжные читаем OCR'ом и вставляем на их места.
    page_types = classify_pages(pdf_path)
    document, page_images = parse_prose_pages(pdf_path, page_types)
    if document_id:
        document["document_id"] = document_id
    insert_drawing_pages(document, pdf_path, page_types)

    # Папка документа: data/cli_output/<document_id>/ или переданный пул
    doc_dir = doc_dir or (CLI_OUTPUT_DIR / document["document_id"])
    doc_dir.mkdir(parents=True, exist_ok=True)

    # Решаем, какие страницы сохранять, и сохраняем их.
    # Первую страницу сохраняем всегда — describe.py берёт с неё название
    # и описание документа, даже если визуалов там нет.
    pages_to_save = collect_pages_to_save(document)
    pages_to_save.add(1)
    pages_dir = pages_dir or (doc_dir / "pages")
    saved_paths = save_page_images(page_images, pages_to_save, pages_dir)

    # Дозаполняем поля у блоков figure/table (пути к картинкам, соседи)
    enrich_visual_blocks(document, pages_to_save)

    # Сохраняем итоговый JSON — уже с заполненными путями
    output_path = doc_dir / "document.json"
    save_json_atomic(output_path, document)

    # Отчёт
    total_blocks = sum(len(p["blocks"]) for p in document["pages"])
    print("\nГотово!")
    print(f"  Файл:    {output_path}")
    print(f"  Страниц: {len(document['pages'])}")
    print(f"  Блоков:  {total_blocks}")
    print(f"  Сохранено картинок страниц: {len(saved_paths)} (в {pages_dir}/)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Использование: python -m pipeline.parse <pdf_name>")
        print("Пример:        python -m pipeline.parse MVL649")
        sys.exit(1)
    process(sys.argv[1])
