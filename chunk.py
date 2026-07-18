"""
Этап 3: нарезка документа на смысловые чанки.

Берёт document.json (структура из main.py) и descriptions.json (vision-описания
из describe.py), в памяти сливает описания в блоки документа и нарезает на чанки.
Результат сохраняет в chunks.json.

Запускать ПОСЛЕ main.py и describe.py:
    python main.py       # этап 1: парсинг PDF
    python describe.py   # этап 2: описание схем
    python chunk.py      # этап 3: нарезка на чанки
"""

import json
import sys
from pathlib import Path

from backend.core.paths import RAW_DATA_DIR
from pdf_processing.chunker import build_chunks_routed
from pdf_processing.parser import make_document_id


def load_json(json_path: Path) -> dict:
    """Читает JSON-файл в словарь."""
    with open(json_path, encoding="utf-8") as f:
        return json.load(f)


def save_chunks(chunks: list[dict], json_path: Path) -> None:
    """Сохраняет список чанков в JSON-файл."""
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(chunks, f, ensure_ascii=False, indent=2)


def merge_descriptions(document: dict, descriptions: dict) -> None:
    """
    Сливает данные из descriptions.json в document (на месте).

    document_title и document_summary кладёт на верхний уровень документа;
    block_descriptions разносит по блокам в поле description по block_id.
    chunker дальше работает как раньше.
    """
    document["document_title"] = descriptions.get("document_title", "")
    document["document_summary"] = descriptions.get("document_summary", "")

    block_descriptions = descriptions.get("block_descriptions", {})
    for page in document["pages"]:
        for block in page["blocks"]:
            description = block_descriptions.get(block["block_id"])
            if description:
                block["description"] = description


def process(pdf_name: str, doc_dir: Path | None = None) -> None:
    """
    Нарезает документ на чанки и сохраняет chunks.json.
    pdf_name — то же имя, что передавалось в main.py (например, MVL649).
    doc_dir — папка документа; по умолчанию data/raw_data/<id> (нормы),
    архив проектов передаёт свою (projects_data/<slug>).
    """
    doc_dir = doc_dir or (RAW_DATA_DIR / make_document_id(pdf_name))
    document_path = doc_dir / "document.json"
    descriptions_path = doc_dir / "descriptions.json"
    chunks_path = doc_dir / "chunks.json"

    if not descriptions_path.exists():
        print(f"[!] Нет файла {descriptions_path}")
        print("    Сначала запусти: python describe.py <pdf_name>")
        sys.exit(1)

    document = load_json(document_path)
    descriptions = load_json(descriptions_path)

    # Вливаем описания в документ в памяти — chunker дальше работает как раньше
    merge_descriptions(document, descriptions)

    print(f"Документ: {document['document_name']}")
    print("Нарезаю на чанки...")

    chunks = build_chunks_routed(document)
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
