"""Бизнес-логика модуля settings."""

import json
import os
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core import library_cache
from backend.modules.settings.models import Setting


LIBRARY_PATH_KEY = "library_path"  # легаси: одна папка (мигрируем в список ниже)
# Список папок библиотеки (JSON). Пришёл на смену единственному library_path:
# юзер может подключить несколько папок сразу (свои нормы + папка фирмы).
LIBRARY_PATHS_KEY = "library_paths"
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


def _validate_dir(raw_path: str) -> Path:
    """Нормализует пользовательскую строку пути в абсолютный путь к папке.

    `~` и относительные пути разворачиваем через expanduser+resolve. Бросает
    ValueError, если путь не существует или это не папка.
    """
    path = Path(raw_path).expanduser().resolve()
    if not path.exists():
        raise ValueError(f"Путь не существует: {path}")
    if not path.is_dir():
        raise ValueError(f"Это не папка: {path}")
    return path


def _set_path(db: Session, key: str, raw_path: str) -> str:
    """Валидирует и сохраняет путь-папку под ключом key. Общее для обеих библиотек."""
    path = _validate_dir(raw_path)

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
    """Сохраняет путь к папке библиотеки юзера.

    Сбрасывает кеш поиска: индексы теперь лежат в <папка>/.search_index,
    смена папки меняет и пул индексов.
    """
    path = _set_path(db, LIBRARY_PATH_KEY, raw_path)
    library_cache.invalidate()
    return path


def get_library_paths(db: Session) -> list[str]:
    """Список папок библиотеки. Пустой список — ни одной не задано.

    Мигрирует со старого единственного `library_path`: если списка ещё нет,
    но легаси-путь задан — переносим его в список (один раз) и сохраняем.
    """
    setting = db.scalar(select(Setting).where(Setting.key == LIBRARY_PATHS_KEY))
    if setting and setting.value:
        try:
            paths = json.loads(setting.value)
            if isinstance(paths, list):
                return [str(p) for p in paths]
        except (ValueError, TypeError):
            pass  # битое значение — трактуем как «списка нет», попробуем миграцию

    legacy = get_library_path(db)
    if legacy:
        _save_library_paths(db, [legacy])
        return [legacy]
    return []


def _save_library_paths(db: Session, paths: list[str]) -> None:
    """Пишет список папок в настройки (JSON)."""
    value = json.dumps(paths, ensure_ascii=False)
    setting = db.scalar(select(Setting).where(Setting.key == LIBRARY_PATHS_KEY))
    if setting is None:
        db.add(Setting(key=LIBRARY_PATHS_KEY, value=value))
    else:
        setting.value = value
    db.commit()


def add_library_path(db: Session, raw_path: str) -> list[str]:
    """Добавляет папку в список библиотеки. Валидирует, что папка существует.

    Дубли пути игнорируем (idempotent). Сбрасывает кеш поиска — в пул войдут
    индексы новой папки.
    """
    path = str(_validate_dir(raw_path))
    paths = get_library_paths(db)
    if path not in paths:
        paths.append(path)
        _save_library_paths(db, paths)
        library_cache.invalidate()
    return paths


def remove_library_path(db: Session, raw_path: str) -> list[str]:
    """Убирает папку из списка (по нормализованному пути). Индексы в
    `.search_index` на диске НЕ трогаем — только отключаем папку от поиска."""
    target = str(Path(raw_path).expanduser().resolve())
    paths = [p for p in get_library_paths(db) if p != target]
    _save_library_paths(db, paths)
    library_cache.invalidate()
    return paths


def update_library_path(db: Session, old_raw: str, new_raw: str) -> list[str]:
    """Заменяет папку в списке на новую (правка пути), сохраняя её позицию.

    Валидирует, что новая папка существует. Если старого пути в списке нет —
    просто добавляет новый (idempotent). Документы привязаны к метке папки
    (folder_id из meta.json), а не к строке пути, поэтому если новый путь
    указывает на ту же физическую папку — индексы переподключатся сами.
    """
    new_path = str(_validate_dir(new_raw))
    old_path = str(Path(old_raw).expanduser().resolve())

    result: list[str] = []
    seen: set[str] = set()
    replaced = False
    for p in get_library_paths(db):
        candidate = new_path if p == old_path else p
        if p == old_path:
            replaced = True
        if candidate not in seen:  # дедуп, если new уже был в списке
            result.append(candidate)
            seen.add(candidate)
    if not replaced and new_path not in seen:
        result.append(new_path)

    _save_library_paths(db, result)
    library_cache.invalidate()
    return result


def get_shared_library_path(db: Session) -> str | None:
    """Возвращает путь к папке общей базы или None, если не задан."""
    setting = db.scalar(select(Setting).where(Setting.key == SHARED_LIBRARY_PATH_KEY))
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
