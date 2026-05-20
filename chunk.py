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
import sys
from pathlib import Path

from pdf_processing.chunker import build_chunks
from pdf_processing.parser import make_document_id


def load_document(json_path: Path) -> dict:
    """Читает document.json в словарь."""
    with open(json_path, encoding="utf-8") as f:
        return json.load(f)


def save_chunks(chunks: list[dict], json_path: Path) -> None:
    """Сохраняет список чанков в JSON-файл."""
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(chunks, f, ensure_ascii=False, indent=2)


def process(pdf_name: str) -> None:
    """
    Нарезает document.json на чанки и сохраняет chunks.json.
    pdf_name — то же имя, что передавалось в main.py (например, MVL649).
    """
    doc_dir = Path("data/raw_data") / make_document_id(pdf_name)
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
    if len(sys.argv) < 2:
        print("Использование: python chunk.py <pdf_name>")
        print("Пример:        python chunk.py MVL649")
        sys.exit(1)
    process(sys.argv[1])