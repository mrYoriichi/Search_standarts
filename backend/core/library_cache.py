"""In-memory кеш библиотеки (чанки + эмбеддинги).

Читать chunks.json и embeddings.json всех документов на КАЖДЫЙ вопрос дорого
(на 200 документах это сотни МБ с диска перед каждым ответом). Документы между
вопросами не меняются — поэтому грузим один раз и держим в памяти.

При изменении библиотеки (документ обработан / удалён / переименован /
переиндексирован) вызывается invalidate() — следующий get_library() перечитает
диск заново.

Загруженные данные считаем «только для чтения»: поиск и фильтрация их не мутируют
(filter_library создаёт новые списки), поэтому отдавать один и тот же объект разным
запросам безопасно.
"""

import os
import threading
from pathlib import Path

import numpy as np

from ask import EmptyLibraryError, load_library
from indexing.bm25_index import tokenize_chunk
from backend.core import index_store
from backend.core.paths import PROJECTS_DATA_DIR, RAW_DATA_DIR


# Пул юзера: индексы локально обработанных документов.
DATA_ROOT = RAW_DATA_DIR

# Кеш и замок к нему. Запросы FastAPI и фоновый pipeline работают в разных
# потоках — замок защищает от гонки при одновременной загрузке/сбросе.
_lock = threading.Lock()
_cache: tuple[list[dict], dict] | None = None
# Токены BM25 по chunk_id. Считаются один раз; на каждый вопрос строим BM25 из
# них, а не токенизируем корпус заново. Сбрасывается вместе с _cache.
_tokens_cache: dict[str, list[str]] | None = None
# Отпечаток общих папок на момент загрузки кеша (см. _current_fingerprint).
_fingerprint: dict[str, int] | None = None


def _library_index_roots() -> list[Path]:
    """Корни .search_index всех папок библиотеки (включая недоступные).

    Новый пул (этап 4): индексы лежат рядом с PDF юзера, не в data/raw_data.
    chunk_id несёт метку папки (`{folder_id}__…`), поэтому чанки разных папок
    не сталкиваются в слитом пуле. Существование НЕ проверяем: _load_merged
    пропускает отсутствующие корни сам, а отпечатку нужны и недоступные —
    чтобы отличать «диск отвалился» от «документы удалили».
    """
    from backend.core.database import SessionLocal
    from backend.modules.settings import service as settings_service

    db = SessionLocal()
    try:
        library_paths = settings_service.get_library_paths(db)
    finally:
        db.close()
    roots = []
    seen: list[Path] = []
    for library_path in library_paths:
        p = Path(library_path)
        if any(index_store.same_dir(p, s) for s in seen):
            continue  # та же физическая папка под вторым путём — чанки не двоим
        seen.append(p)
        roots.append(index_store.index_root(p))
    return roots


def _load_merged() -> tuple[list[dict], dict]:
    """Сливает пулы в один (chunks, embeddings_index): нормы юзера
    (папки библиотеки) и архив проектов.

    Все пулы обязаны быть на одной модели эмбеддингов — векторы из разных
    моделей несравнимы. Пустой/отсутствующий пул тихо пропускаем; ошибка только
    если готовых документов нет нигде.
    """
    roots = [DATA_ROOT]
    roots.extend(_library_index_roots())
    if PROJECTS_DATA_DIR.exists():
        roots.append(PROJECTS_DATA_DIR)

    all_chunks: list[dict] = []
    all_chunk_ids: list[str] = []
    matrices: list[np.ndarray] = []
    model: str | None = None
    for root in roots:
        if not root.exists():
            continue
        try:
            chunks, index = load_library(root)
        except EmptyLibraryError:
            continue  # в этом корне нет готовых документов — не страшно
        # Прочие RuntimeError (смешанные модели внутри корня) летят наверх:
        # роутер отдаст 400 с текстом вместо молчаливого выпадения папки.
        if model is None:
            model = index["model"]
        elif model != index["model"]:
            # Текст уходит юзеру в UI (роутер отдаёт его как detail) — по-чешски.
            raise RuntimeError(
                "Části knihovny jsou indexovány různými modely embeddingů "
                f"({model} ≠ {index['model']}) a nejsou kompatibilní — "
                "přeindexujte starší složku."
            )
        all_chunks.extend(chunks)
        all_chunk_ids.extend(index["chunk_ids"])
        matrices.append(index["matrix"])

    if not all_chunks:
        # Текст уходит юзеру в UI (роутер отдаёт его как detail) — по-чешски.
        raise RuntimeError(
            "V knihovně zatím není žádný hotový dokument — "
            "nejdřív složku naskenujte a naindexujte."
        )
    # Матрицы пулов уже нормированы (build_matrix_index) — просто составляем их
    # в одну. Порядок строк совпадает с порядком all_chunk_ids.
    matrix = np.vstack(matrices)
    return all_chunks, {"model": model, "chunk_ids": all_chunk_ids, "matrix": matrix}


def _current_fingerprint(prev: dict[str, int] | None) -> dict[str, int]:
    """Отпечаток общих папок: mtime embeddings.json каждого документа.

    Только корни библиотек (_library_index_roots): их может переписать ДРУГАЯ
    машина через общую сетевую папку, и наш локальный invalidate() этого не
    видит. Локальные пулы (data/raw_data, projects_data) мутирует только этот
    процесс — он и так зовёт invalidate(). embeddings.json — последний файл
    пайплайна, его смена означает завершённую переиндексацию; новый или
    удалённый документ — появившийся/пропавший ключ.

    НЕДОСТУПНЫЙ корень (сетевой диск отвалился, VPN) ≠ «документы удалили»:
    переносим его записи из прошлого отпечатка prev — тёплый кеш продолжает
    отвечать полным корпусом, а после возврата диска сравнение честное.
    """
    fp: dict[str, int] = {}
    for root in _library_index_roots():
        try:
            slug_dirs = list(root.iterdir())
        except OSError:
            if prev:
                prefix = str(root) + os.sep
                fp.update({k: v for k, v in prev.items() if k.startswith(prefix)})
            continue
        for d in slug_dirs:
            emb = d / "embeddings.json"
            try:
                fp[str(emb)] = emb.stat().st_mtime_ns
            except OSError:
                continue
    return fp


def _ensure_fresh_locked() -> None:
    """Под _lock: сбрасывает и перечитывает кеш, если общие папки изменились."""
    global _cache, _tokens_cache, _fingerprint
    fp = _current_fingerprint(_fingerprint)
    if _cache is not None and fp != _fingerprint:
        _cache = None
        _tokens_cache = None
    if _cache is None:
        # Отпечаток снимаем ДО загрузки: запись, гонящаяся с чтением, даст
        # расхождение и честную перечитку на следующем вопросе.
        _fingerprint = fp
        _cache = _load_merged()


def get_library() -> tuple[list[dict], dict]:
    """Возвращает (chunks, embeddings_index). При первом обращении читает диск."""
    with _lock:
        _ensure_fresh_locked()
        return _cache


def get_library_with_tokens() -> tuple[list[dict], dict, dict[str, list[str]]]:
    """Возвращает (chunks, embeddings_index, {chunk_id: токены BM25}) РАЗОМ.

    Всё берётся под одним локом — chunks и токены гарантированно одного
    поколения кеша. Раздельные вызовы get_library() + «get_tokens()» ловили
    гонку: invalidate() между ними давал токены нового поколения к чанкам
    старого → KeyError на вопросе. Токены считаются один раз; на каждый вопрос
    BM25 собирается из них (build_bm25_from_tokens) без токенизации корпуса.
    """
    global _tokens_cache
    with _lock:
        _ensure_fresh_locked()
        if _tokens_cache is None:
            _tokens_cache = {c["chunk_id"]: tokenize_chunk(c) for c in _cache[0]}
        return _cache[0], _cache[1], _tokens_cache


def invalidate() -> None:
    """Сбрасывает кеши — следующий get_library()/get_tokens() перечитает диск."""
    global _cache, _tokens_cache, _fingerprint
    with _lock:
        _cache = None
        _tokens_cache = None
        _fingerprint = None
