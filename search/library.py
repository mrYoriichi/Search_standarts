"""Загрузка и фильтрация пула документов (chunks.json + embeddings.json).

Общая часть поиска: её используют и CLI-сценарий (cli/ask.py), и кеш
библиотеки приложения (backend/core/library_cache.py).
"""

import json
from pathlib import Path

import numpy as np

from backend.core.ui_messages import msg
from indexing.embeddings_index import build_matrix_index


def load_chunks(json_path: Path) -> list[dict]:
    """Читает chunks.json в список чанков."""
    with open(json_path, encoding="utf-8") as f:
        return json.load(f)


def load_index(json_path: Path) -> dict:
    """Читает векторный индекс из файла."""
    with open(json_path, encoding="utf-8") as f:
        return json.load(f)


class EmptyLibraryError(RuntimeError):
    """В корне нет ни одного готового документа — такой корень можно тихо
    пропустить при слиянии пулов (в отличие от несовместимых моделей)."""


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

        # Сверяем модель эмбеддингов. Текст летит в UI через 400.
        if model is None:
            model = index_model
        elif model != index_model:
            raise RuntimeError(
                msg(
                    "lib.mixed_models_doc",
                    doc=doc_dir.name,
                    model_a=index_model,
                    model_b=model,
                )
            )

        all_chunks.extend(chunks)
        all_items.extend(index_items)

    if not all_chunks:
        raise EmptyLibraryError(f"В {data_root} нет ни одного готового документа.")

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
