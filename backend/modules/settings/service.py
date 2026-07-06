"""Бизнес-логика модуля settings."""

import json
import os
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core import library_cache
from backend.modules.settings.models import Setting


LIBRARY_PATH_KEY = "library_path"
# Папка общей базы норм от владельца (read-only): индексы + оригиналы PDF.
# Отдельный пул, не сканируется. См. «Два пула документов» в PROJECT_STATE.
SHARED_LIBRARY_PATH_KEY = "shared_library_path"
# Закреплённые документы общей базы. У них нет строки в documents (пул read-only),
# поэтому пины храним отдельным списком slug'ов (JSON) здесь.
SHARED_PINNED_KEY = "shared_pinned_slugs"
# Папка архива проектов юзера (личный пул). Структура: {проект}/.../файл.pdf,
# проект = папка первого уровня. См. модуль projects.
PROJECTS_PATH_KEY = "projects_library_path"
# Vision-модель для обработки документов (рычаг стоимости: vision ~99% цены дока).
# Дефолт совпадает с VISION_MODEL в pdf_processing/image_description.py.
VISION_MODEL_KEY = "vision_model"
VISION_MODELS = ("gpt-5.5", "gpt-5.4-mini")
DEFAULT_VISION_MODEL = "gpt-5.4-mini"  # дешевле; gpt-5.5 — по выбору в «Knihovna»
OPENAI_KEY_KEY = "openai_api_key"


def _set_path(db: Session, key: str, raw_path: str) -> str:
    """Валидирует и сохраняет путь-папку под ключом key. Общее для обеих библиотек.

    На вход — пользовательская строка (с `~` или относительная); нормализуем в
    абсолютный путь через expanduser+resolve. Бросает ValueError, если путь не
    существует или это не папка.
    """
    path = Path(raw_path).expanduser().resolve()
    if not path.exists():
        raise ValueError(f"Путь не существует: {path}")
    if not path.is_dir():
        raise ValueError(f"Это не папка: {path}")

    setting = db.scalar(select(Setting).where(Setting.key == key))
    if setting is None:
        setting = Setting(key=key, value=str(path))
        db.add(setting)
    else:
        setting.value = str(path)
    db.commit()
    return str(path)


def get_library_path(db: Session) -> str | None:
    """Возвращает текущий путь к папке библиотеки или None, если не задан."""
    setting = db.scalar(select(Setting).where(Setting.key == LIBRARY_PATH_KEY))
    return setting.value if setting else None


def set_library_path(db: Session, raw_path: str) -> str:
    """Сохраняет путь к папке библиотеки юзера."""
    return _set_path(db, LIBRARY_PATH_KEY, raw_path)


def get_shared_library_path(db: Session) -> str | None:
    """Возвращает путь к папке общей базы или None, если не задан."""
    setting = db.scalar(
        select(Setting).where(Setting.key == SHARED_LIBRARY_PATH_KEY)
    )
    return setting.value if setting else None


def set_shared_library_path(db: Session, raw_path: str) -> str:
    """Сохраняет путь к папке общей базы.

    Сбрасывает кеш библиотеки: в слитый пул поиска должны попасть индексы
    из новой общей базы (см. library_cache).
    """
    path = _set_path(db, SHARED_LIBRARY_PATH_KEY, raw_path)
    library_cache.invalidate()
    return path


def get_shared_pinned_slugs(db: Session) -> set[str]:
    """Множество slug'ов закреплённых документов общей базы."""
    setting = db.scalar(select(Setting).where(Setting.key == SHARED_PINNED_KEY))
    if not setting or not setting.value:
        return set()
    try:
        return set(json.loads(setting.value))
    except (ValueError, TypeError):
        return set()  # битое значение трактуем как «пинов нет»


def toggle_shared_pin(db: Session, slug: str) -> bool:
    """Переключает закрепление документа общей базы. Возвращает новое состояние."""
    pinned = get_shared_pinned_slugs(db)
    now_pinned = slug not in pinned
    if now_pinned:
        pinned.add(slug)
    else:
        pinned.discard(slug)

    value = json.dumps(sorted(pinned))
    setting = db.scalar(select(Setting).where(Setting.key == SHARED_PINNED_KEY))
    if setting is None:
        db.add(Setting(key=SHARED_PINNED_KEY, value=value))
    else:
        setting.value = value
    db.commit()
    return now_pinned


def get_projects_path(db: Session) -> str | None:
    """Возвращает путь к папке архива проектов или None, если не задан."""
    setting = db.scalar(select(Setting).where(Setting.key == PROJECTS_PATH_KEY))
    return setting.value if setting else None


def set_projects_path(db: Session, raw_path: str) -> str:
    """Сохраняет путь к папке архива проектов юзера."""
    return _set_path(db, PROJECTS_PATH_KEY, raw_path)


def get_vision_model(db: Session) -> str:
    """Текущая vision-модель для обработки документов. Дефолт, если не задана."""
    setting = db.scalar(select(Setting).where(Setting.key == VISION_MODEL_KEY))
    return setting.value if setting else DEFAULT_VISION_MODEL


def set_vision_model(db: Session, model: str) -> str:
    """Сохраняет выбор vision-модели. Бросает ValueError на неизвестную модель."""
    if model not in VISION_MODELS:
        raise ValueError(f"Неизвестная vision-модель: {model}")
    setting = db.scalar(select(Setting).where(Setting.key == VISION_MODEL_KEY))
    if setting is None:
        db.add(Setting(key=VISION_MODEL_KEY, value=model))
    else:
        setting.value = model
    db.commit()
    return model


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
