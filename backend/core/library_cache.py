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


DATA_ROOT = Path("data/raw_data")

# Кеш и замок к нему. Запросы FastAPI и фоновый pipeline работают в разных
# потоках — замок защищает от гонки при одновременной загрузке/сбросе.
_lock = threading.Lock()
_cache: tuple[list[dict], dict] | None = None


def get_library() -> tuple[list[dict], dict]:
    """Возвращает (chunks, embeddings_index). При первом обращении читает диск."""
    global _cache
    with _lock:
        if _cache is None:
            _cache = load_library(DATA_ROOT)
        return _cache


def invalidate() -> None:
    """Сбрасывает кеш — следующий get_library() перечитает диск."""
    global _cache
    with _lock:
        _cache = None
