"""Атомарная запись JSON: сначала во временный файл, потом переименование.

os.replace внутри одной папки атомарен — читатель никогда не увидит
наполовину записанный файл. Важно для общей сетевой папки .search_index:
обрыв записи оставит максимум мусорный *.tmp, но не битый индекс.
"""

import json
import os
from pathlib import Path


def save_json_atomic(path: Path, data: object) -> None:
    """Записывает data в path через временный файл в той же папке."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        # ensure_ascii=False — чешские символы сохраняются как есть
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
