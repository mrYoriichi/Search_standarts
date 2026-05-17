"""
Этап 3: нарезка документа на смысловые чанки.

Берёт готовый document.json (результат main.py + describe.py),
нарезает на чанки и сохраняет их в chunks.json.

Запускать ПОСЛЕ main.py и describe.py:
    python main.py       # этап 1: парсинг PDF
    python describe.py   # этап 2: описание схем
    python chunk.py      # этап 3: нарезка на чанки
"""
import json
from pathlib import Path

from pdf_processing.chunker import build_chunks


def load_document(json_path: Path) -> dict:
    """Читает document.json в словарь."""
    with open(json_path, encoding="utf-8") as f:
        return json.load(f)


def save_chunks(chunks: list[dict], json_path: Path) -> None:
    """Сохраняет список чанков в JSON-файл."""
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(chunks, f, ensure_ascii=False, indent=2)


def main():
    # Папка документа. Пока имя задаём вручную — позже сделаем аргументом.
    doc_dir = Path("data/raw_data/mvl649")
    document_path = doc_dir / "document.json"
    chunks_path = doc_dir / "chunks.json"

    document = load_document(document_path)

    print(f"Документ: {document['document_name']}")
    print("Нарезаю на чанки...")

    chunks = build_chunks(document)
    save_chunks(chunks, chunks_path)

    # Небольшой отчёт
    total_chars = sum(len(c["text"]) for c in chunks)
    avg_chars = total_chars // len(chunks) if chunks else 0

    print("\nГотово!")
    print(f"  Чанков создано:    {len(chunks)}")
    print(f"  Средний размер:    {avg_chars} символов")
    print(f"  Файл сохранён:     {chunks_path}")


if __name__ == "__main__":
    main()