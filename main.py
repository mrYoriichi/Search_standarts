"""
Точка входа в проект.
Разбирает PDF через pdf_processing.parser и сохраняет результат на диск.
Когда переедем на БД, изменится только функция сохранения — парсер не трогаем.
"""
import json
import sys
from pathlib import Path

from backend.core.paths import PDF_STORAGE_DIR, RAW_DATA_DIR
from pdf_processing.parser import parse_pdf, collect_pages_to_save, enrich_visual_blocks


def save_document_json(document: dict, output_root: Path) -> Path:
    """
    Сохраняет результат разбора в data/raw_data/<document_id>/document.json.
    Возвращает путь к созданному файлу.
    """
    # У каждого документа своя папка с именем = document_id
    doc_dir = output_root / document["document_id"]
    doc_dir.mkdir(parents=True, exist_ok=True)

    output_path = doc_dir / "document.json"
    with open(output_path, "w", encoding="utf-8") as f:
        # ensure_ascii=False — чтобы чешские символы сохранились как есть,
        # а не превратились в \u010c и подобные
        json.dump(document, f, ensure_ascii=False, indent=2)

    return output_path


def save_page_images(
    page_images: dict,
    pages_to_save: set[int],
    doc_dir: Path,
) -> dict[int, str]:
    """
    Сохраняет указанные страницы как PNG в подпапку pages/.
    Возвращает словарь {номер_страницы: относительный_путь} —
    он пригодится, чтобы вписать пути в JSON.

    page_images   — все картинки страниц из парсера (PIL.Image).
    pages_to_save — какие именно страницы реально сохраняем.
    doc_dir       — папка документа (data/raw_data/<document_id>/).
    """
    pages_dir = doc_dir / "pages"
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
) -> None:
    """
    Разбирает один PDF и сохраняет результат в data/raw_data/<document_id>/.
    pdf_name — имя файла БЕЗ расширения.
    pdf_path — полный путь к PDF. Если не задан, берётся data/pdfs/<pdf_name>.pdf
    (старое поведение для CLI и upload-flow). Сканирование папки библиотеки
    передаёт сюда путь к PDF прямо из папки юзера.
    doc_dir — папка результатов. Если не задана — data/raw_data/<document_id>
    (нормы). Архив проектов передаёт свой пул (projects_data/<slug>).
    document_id — переопределяет id из имени файла. Архив проектов передаёт
    slug вида {проект}__{файл} — имена файлов между проектами повторяются.
    """
    if pdf_path is None:
        pdf_path = str(PDF_STORAGE_DIR / f"{pdf_name}.pdf")

    print(f"Читаю {pdf_path}, подожди...")
    document, page_images = parse_pdf(pdf_path)
    if document_id:
        document["document_id"] = document_id

    # Папка документа: data/raw_data/<document_id>/ или переданный пул
    doc_dir = doc_dir or (RAW_DATA_DIR / document["document_id"])
    doc_dir.mkdir(parents=True, exist_ok=True)

    # Решаем, какие страницы сохранять, и сохраняем их.
    # Первую страницу сохраняем всегда — describe.py берёт с неё название
    # и описание документа, даже если визуалов там нет.
    pages_to_save = collect_pages_to_save(document)
    pages_to_save.add(1)
    saved_paths = save_page_images(page_images, pages_to_save, doc_dir)

    # Дозаполняем поля у блоков figure/table (пути к картинкам, соседи)
    enrich_visual_blocks(document, pages_to_save)

    # Сохраняем итоговый JSON — уже с заполненными путями
    output_path = doc_dir / "document.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(document, f, ensure_ascii=False, indent=2)

    # Отчёт
    total_blocks = sum(len(p["blocks"]) for p in document["pages"])
    print("\nГотово!")
    print(f"  Файл:    {output_path}")
    print(f"  Страниц: {len(document['pages'])}")
    print(f"  Блоков:  {total_blocks}")
    print(f"  Сохранено картинок страниц: {len(saved_paths)} (в {doc_dir}/pages/)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Использование: python main.py <pdf_name>")
        print("Пример:        python main.py MVL649")
        sys.exit(1)
    process(sys.argv[1])