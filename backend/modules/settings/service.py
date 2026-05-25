"""Бизнес-логика модуля settings."""

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.modules.settings.models import Setting


LIBRARY_PATH_KEY = "library_path"


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
