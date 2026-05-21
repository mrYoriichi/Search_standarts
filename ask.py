"""
Этап 6: запрос к системе.

Сканирует data/raw_data/, подгружает чанки и эмбеддинги ВСЕХ подготовленных
документов, ищет гибридным поиском по объединённой библиотеке, генерирует
ответ через LLM со ссылками на источник.

Запускать после того, как для каждого нужного документа прошёл полный
пайплайн (main.py → describe.py → chunk.py → index.py):
    python ask.py
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
DATA_ROOT = Path("data/raw_data")


def load_chunks(json_path: Path) -> list[dict]:
    """Читает chunks.json в список чанков."""
    with open(json_path, encoding="utf-8") as f:
        return json.load(f)


def load_index(json_path: Path) -> dict:
    """Читает векторный индекс из файла."""
    with open(json_path, encoding="utf-8") as f:
        return json.load(f)


def load_library(data_root: Path) -> tuple[list[dict], dict]:
    """
    Объединяет чанки и эмбеддинги всех готовых документов в один пул.

    Сканирует подпапки data_root, у каждой берёт chunks.json и embeddings.json.
    Папки без полного набора файлов (пайплайн не закончен) пропускаются.

    Все документы должны быть проиндексированы ОДНОЙ моделью эмбеддингов —
    векторы из разных моделей несравнимы. Если встретим разные модели,
    падаем с понятной ошибкой.

    Возвращает (chunks, embeddings_index) — тот же формат, что и для одного
    документа, чтобы остальной код (BM25, гибридный поиск) не менялся.
    """
    all_chunks: list[dict] = []
    all_items: list[dict] = []
    model: str | None = None

    for doc_dir in sorted(data_root.iterdir()):
        if not doc_dir.is_dir():
            continue
        chunks_path = doc_dir / "chunks.json"
        index_path = doc_dir / "embeddings.json"
        if not chunks_path.exists() or not index_path.exists():
            # Пайплайн ещё не закончен для этого документа — тихо пропускаем
            continue

        chunks = load_chunks(chunks_path)
        index = load_index(index_path)

        # Сверяем модель эмбеддингов
        if model is None:
            model = index["model"]
        elif model != index["model"]:
            raise RuntimeError(
                f"Документ {doc_dir.name} построен на модели {index['model']}, "
                f"а раньше встретилась модель {model}. Перестрой векторный индекс."
            )

        all_chunks.extend(chunks)
        all_items.extend(index["items"])

    if not all_chunks:
        raise RuntimeError(f"В {data_root} нет ни одного готового документа.")

    return all_chunks, {"model": model, "items": all_items}


def main():
    chunks, embeddings_index = load_library(DATA_ROOT)

    # Сколько документов и чанков подгрузили — пользователю полезно видеть
    doc_ids = sorted({c["document_id"] for c in chunks})
    print(f"Библиотека: документов {len(doc_ids)}, чанков {len(chunks)}.")
    print(f"  {', '.join(doc_ids)}")

    # BM25-индекс строим из объединённого пула на лету
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
