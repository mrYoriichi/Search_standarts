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
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from backend.core.paths import RAW_DATA_DIR
from indexing.embeddings_index import build_embeddings_index, EMBEDDING_MODEL
from jsonio import save_json_atomic
from pdf_processing.parser import make_document_id
from pricing import embedding_cost


def load_chunks(json_path: Path) -> list[dict]:
    """Читает chunks.json в список чанков."""
    with open(json_path, encoding="utf-8") as f:
        return json.load(f)


def save_index(index: dict, json_path: Path) -> None:
    """Сохраняет векторный индекс в JSON-файл."""
    save_json_atomic(json_path, index)


def process(pdf_name: str, doc_dir: Path | None = None) -> None:
    """
    Строит векторный индекс по chunks.json и сохраняет embeddings.json.
    pdf_name — то же имя, что передавалось в main.py (например, MVL649).
    doc_dir — папка документа; по умолчанию data/raw_data/<id> (нормы),
    архив проектов передаёт свою (projects_data/<slug>).
    """
    doc_dir = doc_dir or (RAW_DATA_DIR / make_document_id(pdf_name))
    chunks_path = doc_dir / "chunks.json"
    index_path = doc_dir / "embeddings.json"
    document_path = doc_dir / "document.json"

    chunks = load_chunks(chunks_path)

    # Для метрики "$ за страницу" нужно общее число страниц документа —
    # читаем его из document.json (там len(pages) — это страницы PDF).
    with open(document_path, encoding="utf-8") as f:
        document = json.load(f)
    total_pages = len(document["pages"])

    print(f"Чанков загружено: {len(chunks)}")
    print(f"Модель: {EMBEDDING_MODEL}")
    print("Строю векторный индекс (запрос к OpenAI)...")

    index, tokens = build_embeddings_index(chunks)
    save_index(index, index_path)

    print("\nГотово!")
    print(f"  Векторов сохранено: {len(index['items'])}")
    print(f"  Файл: {index_path}")

    # ---- Сводка по стоимости ----
    usd = embedding_cost(tokens)
    print("\n=== Стоимость embeddings ===")
    print(f"  Страниц в документе: {total_pages}")
    print(f"  Чанков:              {len(chunks)}")
    print(f"  Токены:              {tokens}")
    print(f"  ИТОГО embeddings:                                  ${usd:.4f}")
    if total_pages:
        print(
            f"  $ на страницу (embeddings):                        ${usd / total_pages:.4f}"
        )


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Использование: python index.py <pdf_name>")
        print("Пример:        python index.py MVL649")
        sys.exit(1)
    process(sys.argv[1])
