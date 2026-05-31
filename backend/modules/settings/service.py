"""Бизнес-логика модуля settings."""

import os
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.modules.settings.models import Setting


LIBRARY_PATH_KEY = "library_path"
OPENAI_KEY_KEY = "openai_api_key"


def get_library_path(db: Session) -> str | None:
    """Возвращает текущий путь к папке библиотеки или None, если не задан."""
    setting = db.scalar(select(Setting).where(Setting.key == LIBRARY_PATH_KEY))
    return setting.value if setting else None


def set_library_path(db: Session, raw_path: str) -> str:
    """Сохраняет путь к папке библиотеки.

    Валидирует, что путь существует и это папка. Бросает ValueError при ошибке.
    На вход — пользовательская строка (например, с `~` или относительная);
    нормализуем в абсолютный путь через expanduser+resolve.
    """
    path = Path(raw_path).expanduser().resolve()
    if not path.exists():
        raise ValueError(f"Путь не существует: {path}")
    if not path.is_dir():
        raise ValueError(f"Это не папка: {path}")

    setting = db.scalar(select(Setting).where(Setting.key == LIBRARY_PATH_KEY))
    if setting is None:
        setting = Setting(key=LIBRARY_PATH_KEY, value=str(path))
        db.add(setting)
    else:
        setting.value = str(path)
    db.commit()
    return str(path)


def get_openai_key(db: Session) -> str | None:
    """Возвращает сохранённый ключ OpenAI или None, если не задан."""
    setting = db.scalar(select(Setting).where(Setting.key == OPENAI_KEY_KEY))
    return setting.value if setting else None


def set_openai_key(db: Session, raw_key: str) -> str:
    """Сохраняет ключ OpenAI в БД и сразу кладёт его в окружение.

    Проверяет минимальный формат (`sk-...`). Запись в `os.environ` нужна, чтобы
    следующий же вызов `OpenAI()` (поиск, индексация) взял новый ключ без
    перезапуска — клиенты создаются лениво внутри функций.
    """
    key = raw_key.strip()
    if not key.startswith("sk-"):
        raise ValueError("Ключ OpenAI должен начинаться с 'sk-'")

    setting = db.scalar(select(Setting).where(Setting.key == OPENAI_KEY_KEY))
    if setting is None:
        setting = Setting(key=OPENAI_KEY_KEY, value=key)
        db.add(setting)
    else:
        setting.value = key
    db.commit()
    os.environ["OPENAI_API_KEY"] = key
    return key


def mask_key(key: str) -> str:
    """Маскирует ключ для показа на фронте: светим только последние 4 символа."""
    tail = key[-4:] if len(key) >= 4 else key
    return f"sk-…{tail}"


def apply_openai_key_to_env(db: Session) -> None:
    """На старте: если ключ есть в БД, кладём его в окружение для `OpenAI()`.

    БД — источник истины. Если ключа нет, окружение не трогаем — остаётся
    запасной вариант из `.env` (удобно при разработке).
    """
    key = get_openai_key(db)
    if key:
        os.environ["OPENAI_API_KEY"] = key
