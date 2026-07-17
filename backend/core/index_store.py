"""Индексы в папке библиотеки: <папка>/.search_index/{slug}/.

Источник правды публичной версии — сама папка с PDF: артефакты индекса лежат
рядом с документами в скрытой подпапке .search_index, БД — только локальный
кеш статусов. Один юзер индексирует папку на сетевом диске — остальные
подключают её и ищут без трат («усыновление» готовых индексов при скане).

meta.json — паспорт папки: модель эмбеддингов, версия формата, постоянный id
папки. Id одинаков у всех машин независимо от пути монтирования — им будем
префиксовать chunk_id в кеше поиска, когда папок станет несколько.

Файлы юзера не трогаем (решение №16): пишем ТОЛЬКО внутрь .search_index/.
"""

import json
import uuid
from pathlib import Path

INDEX_DIR_NAME = ".search_index"
META_FILENAME = "meta.json"
# Поднимать при несовместимой смене формата артефактов — старые индексы
# перестанут «усыновляться» и будут переиндексированы.
FORMAT_VERSION = 1


def index_root(library_path: Path) -> Path:
    """Корень индексов папки библиотеки."""
    return library_path / INDEX_DIR_NAME


def doc_dir(library_path: Path, slug: str) -> Path:
    """Папка артефактов одного документа."""
    return index_root(library_path) / slug


def read_meta(library_path: Path) -> dict | None:
    """Читает meta.json папки. Нет файла или битый JSON — None."""
    meta_path = index_root(library_path) / META_FILENAME
    try:
        with open(meta_path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def ensure_meta(library_path: Path, embedding_model: str) -> dict:
    """Возвращает meta.json папки, создав его при первом обращении.

    Существующий meta НЕ перезаписывает (id и модель — постоянные свойства
    папки; конфликт модели ловит вызывающий код сравнением полей).
    """
    meta = read_meta(library_path)
    if meta is not None:
        return meta
    meta = {
        "format_version": FORMAT_VERSION,
        "folder_id": uuid.uuid4().hex,
        "embedding_model": embedding_model,
    }
    root = index_root(library_path)
    root.mkdir(parents=True, exist_ok=True)
    with open(root / META_FILENAME, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    return meta


def scoped_slug(folder_id: str, filename_slug: str) -> str:
    """Id документа = метка папки + slug имени файла (`{folder_id}__{file}`).

    Так один и тот же файл в разных папках даёт разные id — не путаются
    (тот же приём, что в архиве проектов: `{проект}__{файл}`). folder_id —
    постоянная метка папки из meta.json, одинаковая на всех машинах, поэтому
    id не зависит от того, куда папка примонтирована.
    """
    return f"{folder_id}__{filename_slug}"


def folder_id_of(slug: str) -> str | None:
    """Достаёт метку папки из id документа. Нет разделителя `__` — None
    (легаси-slug без папки, из старого пула data/raw_data)."""
    folder_id, sep, _ = slug.partition("__")
    return folder_id if sep else None


def has_complete_index(library_path: Path, slug: str) -> bool:
    """Есть ли у документа полный индекс (нужный поиску минимум).

    chunks.json + embeddings.json достаточно: поиск читает только их,
    document.json/descriptions.json нужны лишь при переобработке.
    """
    d = doc_dir(library_path, slug)
    return (d / "chunks.json").exists() and (d / "embeddings.json").exists()
