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

import threading
from pathlib import Path

from ask import load_library
from backend.core.paths import RAW_DATA_DIR


# Пул юзера: индексы локально обработанных документов.
DATA_ROOT = RAW_DATA_DIR

# Кеш и замок к нему. Запросы FastAPI и фоновый pipeline работают в разных
# потоках — замок защищает от гонки при одновременной загрузке/сбросе.
_lock = threading.Lock()
_cache: tuple[list[dict], dict] | None = None


def _shared_data_root() -> Path | None:
    """Корень индексов общей базы (<shared>/raw_data) или None, если не задан.

    Путь к общей базе живёт в настройках (БД). Импорт settings_service —
    ленивый, чтобы не зациклить модули (settings импортирует этот модуль).
    """
    from backend.core.database import SessionLocal
    from backend.modules.settings import service as settings_service

    db = SessionLocal()
    try:
        shared_path = settings_service.get_shared_library_path(db)
    finally:
        db.close()
    if not shared_path:
        return None
    root = Path(shared_path) / "raw_data"
    return root if root.exists() else None


def _load_merged() -> tuple[list[dict], dict]:
    """Сливает пул юзера и общую базу в один (chunks, embeddings_index).

    Оба пула обязаны быть на одной модели эмбеддингов — векторы из разных
    моделей несравнимы. Пустой/отсутствующий пул тихо пропускаем; ошибка только
    если готовых документов нет нигде.
    """
    roots = [DATA_ROOT]
    shared = _shared_data_root()
    if shared is not None:
        roots.append(shared)

    all_chunks: list[dict] = []
    all_items: list[dict] = []
    model: str | None = None
    for root in roots:
        if not root.exists():
            continue
        try:
            chunks, index = load_library(root)
        except RuntimeError:
            continue  # в этом корне нет готовых документов — не страшно
        if model is None:
            model = index["model"]
        elif model != index["model"]:
            raise RuntimeError(
                "Пул юзера и общая база построены разными моделями эмбеддингов "
                f"({model} ≠ {index['model']}). Они несовместимы."
            )
        all_chunks.extend(chunks)
        all_items.extend(index["items"])

    if not all_chunks:
        raise RuntimeError("Нет ни одного готового документа.")
    return all_chunks, {"model": model, "items": all_items}


def get_library() -> tuple[list[dict], dict]:
    """Возвращает (chunks, embeddings_index). При первом обращении читает диск."""
    global _cache
    with _lock:
        if _cache is None:
            _cache = _load_merged()
        return _cache


def invalidate() -> None:
    """Сбрасывает кеш — следующий get_library() перечитает диск."""
    global _cache
    with _lock:
        _cache = None
