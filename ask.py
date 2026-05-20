"""
Этап 6, часть 2: запрос к системе.

Принимает вопрос с клавиатуры, ищет гибридным поиском, генерирует ответ
через LLM со ссылками на источники.

Запускать ПОСЛЕ index.py (нужен готовый embeddings.json):
    python index.py     # этап 4: построение векторного индекса
    python ask.py       # этап 6: спрашиваем
"""
import json
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from indexing.bm25_index import build_bm25_index
from search.hybrid import hybrid_search
from search.answer import generate_answer


# Сколько чанков подаём в LLM (договорились на 5)
TOP_K = 5


def load_chunks(json_path: Path) -> list[dict]:
    """Читает chunks.json в список чанков."""
    with open(json_path, encoding="utf-8") as f:
        return json.load(f)


def load_index(json_path: Path) -> dict:
    """Читает векторный индекс из файла."""
    with open(json_path, encoding="utf-8") as f:
        return json.load(f)


def main():
    # Папка документа. Пока имя задаём вручную — позже сделаем аргументом.
    doc_dir = Path("data/raw_data/mvl649")
    chunks_path = doc_dir / "chunks.json"
    index_path = doc_dir / "embeddings.json"

    # Загрузка данных
    chunks = load_chunks(chunks_path)
    embeddings_index = load_index(index_path)
    # BM25-индекс строим из чанков на лету — он быстрый, на диск не сохраняем
    bm25 = build_bm25_index(chunks)

    # Вопрос с клавиатуры — удобнее, чем менять константу и перезапускать
    question = input("Вопрос: ").strip()
    if not question:
        print("Пустой вопрос.")
        return

    # Гибридный поиск — топ-5 chunk_id'ов с RRF-score
    found = hybrid_search(bm25, embeddings_index, question, top_k=TOP_K)

    print(f"\nНайдено чанков: {len(found)}")
    for chunk_id, score in found:
        print(f"  {chunk_id}  (rrf={score:.4f})")

    # Подтягиваем полные чанки по id, сохраняя порядок поиска
    chunks_by_id = {c["chunk_id"]: c for c in chunks}
    top_chunks = [chunks_by_id[chunk_id] for chunk_id, _ in found]

    # Генерация ответа (запрос к OpenAI)
    print("\nГенерирую ответ...")
    result = generate_answer(question, top_chunks)

    # Печать результата
    print("\n=== Ответ ===")
    print(result["answer"])

    print("\n=== Источники ===")
    if not result["sources"]:
        print("  (нет — модель не нашла ответа в фрагментах)")
    else:
        for src in result["sources"]:
            pages = ", ".join(str(p) for p in src["pages"])
            print(f"  - {src['document']} / {src['section']} / стр. {pages}")


if __name__ == "__main__":
    main()
