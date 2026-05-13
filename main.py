"""
Точка входа в проект.
Разбирает PDF через pdf_processing.parser и сохраняет результат на диск.
Когда переедем на БД, изменится только функция сохранения — парсер не трогаем.
"""
import json
from pathlib import Path

from pdf_processing.parser import parse_pdf


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


def main():
    pdf_path = "data/pdfs/MVL649.pdf"
    output_root = Path("data/raw_data")

    print(f"Читаю {pdf_path}, подожди...")
    document = parse_pdf(pdf_path)

    output_path = save_document_json(document, output_root)

    # Небольшой отчёт пользователю — что получилось
    total_blocks = sum(len(p["blocks"]) for p in document["pages"])
    print("\nГотово!")
    print(f"  Файл:    {output_path}")
    print(f"  Страниц: {len(document['pages'])}")
    print(f"  Блоков:  {total_blocks}")


if __name__ == "__main__":
    main()