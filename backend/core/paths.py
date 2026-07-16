"""Где приложение хранит данные юзера: БД, индексы, настройки.

Зачем: в .exe бинарник лежит в Program Files (при обновлении перезаписывается
целиком), а данные юзера должны это обновление пережить → их место — системный
user-data каталог ОС. В dev (запуск из исходников) держим данные в корне проекта,
как было всегда, чтобы ничего не сломалось.

Один источник правды для путей. Все потребители (database, pipeline, library)
строят пути от DATA_DIR, а не от текущей рабочей директории.
"""

import os
import sys
from pathlib import Path

APP_NAME = "Search_standarts"


def _project_root() -> Path:
    """Корень репозитория: backend/core/paths.py → ../../.."""
    return Path(__file__).resolve().parents[2]


def _system_user_data_dir() -> Path:
    """Системный каталог данных приложения для текущей ОС."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    # Linux/прочее: XDG_DATA_HOME или ~/.local/share
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / APP_NAME


def _bundle_root() -> Path:
    """Корень с упакованными ресурсами (код, собранный фронтенд).

    В .exe PyInstaller распаковывает данные во временную папку sys._MEIPASS.
    В dev — корень проекта. Отличается от DATA_DIR: тут код/статика (только
    чтение), там данные юзера (запись).
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return _project_root()


def _resolve_data_dir() -> Path:
    """Каталог данных.

    Приоритет: явная переменная окружения (её выставляет лаунчер .exe) →
    системный каталог, если запущены из .exe (PyInstaller ставит sys.frozen) →
    корень проекта (dev).
    """
    env = os.environ.get("SEARCH_STANDARTS_DATA_DIR")
    if env:
        return Path(env)
    if getattr(sys, "frozen", False):
        return _system_user_data_dir()
    return _project_root()


# Каталог данных и производные пути. Вычисляются один раз при импорте.
DATA_DIR = _resolve_data_dir()
DB_PATH = DATA_DIR / "app.db"
RAW_DATA_DIR = DATA_DIR / "data" / "raw_data"
PDF_STORAGE_DIR = DATA_DIR / "data" / "pdfs"
# Пул архива проектов: индексы по slug, отдельно от норм (raw_data).
PROJECTS_DATA_DIR = DATA_DIR / "data" / "projects_data"

# Собранный фронтенд (Vite кладёт сюда; в .exe попадает как bundled-ресурс).
FRONTEND_DIST = _bundle_root() / "frontend" / "dist"

# Предзагруженные модели docling (download_models.py → docling_models/).
# Если папка есть — парсер берёт модели из неё и ничего не качает (вариант 2).
DOCLING_MODELS = _bundle_root() / "docling_models"

# Гарантируем, что каталог данных существует (подпапки создаются по мере надобности).
DATA_DIR.mkdir(parents=True, exist_ok=True)
