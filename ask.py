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

import numpy as np

from backend.core.paths import RAW_DATA_DIR
from indexing.bm25_index import build_bm25_index
from indexing.embeddings_index import build_matrix_index
from search.hybrid import hybrid_search
from search.answer import generate_answer


# Сколько чанков подаём в LLM (договорились на 5)
TOP_K = 5
DATA_ROOT = RAW_DATA_DIR


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

    Возвращает (chunks, embeddings_index), где embeddings_index — матричный
    индекс для поиска (см. build_matrix_index): векторы всех документов собраны
    в одну нормированную float32-матрицу.
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

        try:
            chunks = load_chunks(chunks_path)
            index = load_index(index_path)
            index_model = index["model"]
            index_items = index["items"]
        except (OSError, json.JSONDecodeError, KeyError):
            # Битый/недоступный файл индекса не должен класть весь поиск:
            # пропускаем документ, остальная библиотека работает.
            print(f"[!] Битый индекс, пропускаю документ: {doc_dir.name}")
            continue

        # Сверяем модель эмбеддингов
        if model is None:
            model = index_model
        elif model != index_model:
            raise RuntimeError(
                f"Документ {doc_dir.name} построен на модели {index_model}, "
                f"а раньше встретилась модель {model}. Перестрой векторный индекс."
            )

        all_chunks.extend(chunks)
        all_items.extend(index_items)

    if not all_chunks:
        raise RuntimeError(f"В {data_root} нет ни одного готового документа.")

    return all_chunks, build_matrix_index(all_items, model)


def filter_library(
    chunks: list[dict],
    embeddings_index: dict,
    allowed_ids: set[str],
) -> tuple[list[dict], dict]:
    """
    Оставляет в библиотеке только чанки и эмбеддинги из выбранных документов.
    Формат входа/выхода тот же — дальше BM25 и гибридный поиск работают как раньше.

    Матрица эмбеддингов не знает про document_id (только порядок строк ↔
    chunk_ids), поэтому строим булеву маску по chunk_id отобранных чанков и
    режем ей и матрицу, и список chunk_ids одинаково.
    """
    chunks_f = [c for c in chunks if c["document_id"] in allowed_ids]
    allowed_chunk_ids = {c["chunk_id"] for c in chunks_f}

    chunk_ids = embeddings_index["chunk_ids"]
    mask = np.array([cid in allowed_chunk_ids for cid in chunk_ids], dtype=bool)
    return chunks_f, {
        "model": embeddings_index["model"],
        "chunk_ids": [cid for cid, keep in zip(chunk_ids, mask) if keep],
        "matrix": embeddings_index["matrix"][mask],
    }


def select_scope(doc_ids: list[str]) -> set[str]:
    """
    Спрашивает у пользователя, в каких документах искать.

    Пустой ввод — все документы. Иначе принимает номера через запятую
    ("1, 2") или прямо id документа ("mvl649, tp_107"). Незнакомые токены
    игнорируются с предупреждением. Если ничего валидного не выбрано —
    возвращает все документы.
    """
    raw = input(
        'Где искать? (Enter — везде; номера через запятую, напр. "1, 2"; или id): '
    ).strip()
    if not raw:
        return set(doc_ids)

    selected: set[str] = set()
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        # Цифра — номер из списка
        if token.isdigit():
            idx = int(token) - 1
            if 0 <= idx < len(doc_ids):
                selected.add(doc_ids[idx])
                continue
        # Иначе — пытаемся как document_id
        if token in doc_ids:
            selected.add(token)
            continue
        print(f"  [!] Не распознан токен {token!r} — пропущен")

    if not selected:
        print("  Ничего не выбрано — ищу везде.")
        return set(doc_ids)
    return selected


def main():
    chunks, embeddings_index = load_library(DATA_ROOT)

    # Сколько документов и чанков подгрузили — пользователю полезно видеть
    doc_ids = sorted({c["document_id"] for c in chunks})
    print(f"Библиотека: документов {len(doc_ids)}, чанков {len(chunks)}.")
    for i, doc_id in enumerate(doc_ids, start=1):
        print(f"  [{i}] {doc_id}")

    # Выбор области поиска
    allowed_ids = select_scope(doc_ids)
    if allowed_ids != set(doc_ids):
        chunks, embeddings_index = filter_library(chunks, embeddings_index, allowed_ids)
        print(f"Ищу в {len(allowed_ids)} документах, чанков: {len(chunks)}.")

    # BM25-индекс строим из (возможно отфильтрованного) пула на лету
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
