"""
Этап 4: построение векторного индекса по чанкам.

Берёт готовый chunks.json (результат chunk.py),
строит embeddings-индекс через OpenAI и сохраняет в embeddings.json.

BM25-индекс НЕ сохраняем — он строится из chunks.json мгновенно,
тратить место не имеет смысла. Embeddings = запрос к OpenAI (деньги/время).

Запускать ПОСЛЕ chunk.py:
    python main.py      # этап 1: парсинг PDF
    python describe.py  # этап 2: описание схем
    python chunk.py     # этап 3: нарезка на чанки
    python index.py     # этап 4: построение индекса
"""
import json
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from indexing.embeddings_index import build_embeddings_index, EMBEDDING_MODEL


def load_chunks(json_path: Path) -> list[dict]:
    """Читает chunks.json в список чанков."""
    with open(json_path, encoding="utf-8") as f:
        return json.load(f)


def save_index(index: dict, json_path: Path) -> None:
    """Сохраняет векторный индекс в JSON-файл."""
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)


def main():
    # Папка документа. Пока имя задаём вручную — позже сделаем аргументом.
    doc_dir = Path("data/raw_data/mvl649")
    chunks_path = doc_dir / "chunks.json"
    index_path = doc_dir / "embeddings.json"

    chunks = load_chunks(chunks_path)

    print(f"Чанков загружено: {len(chunks)}")
    print(f"Модель: {EMBEDDING_MODEL}")
    print("Строю векторный индекс (запрос к OpenAI)...")

    index = build_embeddings_index(chunks)
    save_index(index, index_path)

    print("\nГотово!")
    print(f"  Векторов сохранено: {len(index['items'])}")
    print(f"  Файл: {index_path}")


if __name__ == "__main__":
    main()
