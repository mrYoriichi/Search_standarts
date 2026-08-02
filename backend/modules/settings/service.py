"""Бизнес-логика модуля settings."""

import json
import os
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core import library_cache, ui_messages
from backend.modules.settings.models import Setting


LIBRARY_PATH_KEY = "library_path"  # легаси: одна папка (мигрируем в список ниже)
# Список папок библиотеки (JSON). Пришёл на смену единственному library_path:
# юзер может подключить несколько папок сразу (свои нормы + папка фирмы).
LIBRARY_PATHS_KEY = "library_paths"
# Папка архива проектов юзера (личный пул). Структура: {проект}/.../файл.pdf,
# проект = папка первого уровня. См. модуль projects.
PROJECTS_PATH_KEY = "projects_library_path"  # легаси: одна папка → список ниже
PROJECTS_PATHS_KEY = "projects_library_paths"
# Vision-модель для обработки документов (рычаг стоимости: vision ~99% цены дока).
# Дефолт совпадает с VISION_MODEL в pdf_processing/image_description.py.
VISION_MODEL_KEY = "vision_model"
VISION_MODELS = ("gpt-5.5", "gpt-5.4-mini")
DEFAULT_VISION_MODEL = "gpt-5.4-mini"  # дешевле; gpt-5.5 — по выбору в «Knihovna»
# Тумблер vision при обработке: ВКЛ (дефолт) = Стандарт (описываем схемы и
# чертежи), ВЫКЛ = «Без LLM» (только OCR/текст, бесплатно). Хранится как "1"/"0".
DESCRIBE_IMAGES_KEY = "describe_images"
OPENAI_KEY_KEY = "openai_api_key"
# Язык интерфейса (cs/en/de): фронт шлёт при переключении, бэкенд использует
# для текстов ошибок (backend/core/ui_messages.py). Дефолт — английский.
UI_LANGUAGE_KEY = "ui_language"
# Язык ОТВЕТА LLM (cs/en/de) — настройка в профиле, независим от языка UI.
ANSWER_LANGUAGE_KEY = "answer_language"


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


# --- Общая механика «список папок» (библиотека и архив устроены одинаково) ---


def _get_path_list(db: Session, list_key: str, legacy_key: str | None) -> list[str]:
    """Список папок под list_key. Пустой — ничего не задано.

    Мигрирует со старого единственного пути под legacy_key: если списка ещё
    нет, но легаси-путь задан — переносим его в список (один раз).
    """
    setting = db.scalar(select(Setting).where(Setting.key == list_key))
    if setting and setting.value:
        try:
            paths = json.loads(setting.value)
            if isinstance(paths, list):
                return [str(p) for p in paths]
        except (ValueError, TypeError):
            pass  # битое значение — трактуем как «списка нет», попробуем миграцию

    if legacy_key is not None:
        legacy = db.scalar(select(Setting).where(Setting.key == legacy_key))
        if legacy and legacy.value:
            _save_path_list(db, list_key, [legacy.value])
            return [legacy.value]
    return []


def _save_path_list(db: Session, list_key: str, paths: list[str]) -> None:
    value = json.dumps(paths, ensure_ascii=False)
    setting = db.scalar(select(Setting).where(Setting.key == list_key))
    if setting is None:
        db.add(Setting(key=list_key, value=value))
    else:
        setting.value = value
    db.commit()


def _add_to_path_list(
    db: Session, list_key: str, legacy_key: str | None, raw_path: str
) -> list[str]:
    """Добавляет папку (валидирует существование). Дубли idempotent. Сброс кеша."""
    path = str(_validate_dir(raw_path))
    paths = _get_path_list(db, list_key, legacy_key)
    if path not in paths:
        paths.append(path)
        _save_path_list(db, list_key, paths)
        library_cache.invalidate()
    return paths


def _remove_from_path_list(
    db: Session, list_key: str, legacy_key: str | None, raw_path: str
) -> list[str]:
    """Убирает папку по нормализованному пути. Индексы на диске не трогаем."""
    target = str(Path(raw_path).expanduser().resolve())
    paths = [p for p in _get_path_list(db, list_key, legacy_key) if p != target]
    _save_path_list(db, list_key, paths)
    library_cache.invalidate()
    return paths


def _update_in_path_list(
    db: Session, list_key: str, legacy_key: str | None, old_raw: str, new_raw: str
) -> list[str]:
    """Правит путь папки на месте (сохраняет позицию, дедупит). Сброс кеша."""
    new_path = str(_validate_dir(new_raw))
    old_path = str(Path(old_raw).expanduser().resolve())

    result: list[str] = []
    seen: set[str] = set()
    replaced = False
    for p in _get_path_list(db, list_key, legacy_key):
        candidate = new_path if p == old_path else p
        if p == old_path:
            replaced = True
        if candidate not in seen:  # дедуп, если new уже был в списке
            result.append(candidate)
            seen.add(candidate)
    if not replaced and new_path not in seen:
        result.append(new_path)

    _save_path_list(db, list_key, result)
    library_cache.invalidate()
    return result


# --- Папки библиотеки норм ---


def get_library_paths(db: Session) -> list[str]:
    """Список папок библиотеки (мигрирует со старого library_path)."""
    return _get_path_list(db, LIBRARY_PATHS_KEY, LIBRARY_PATH_KEY)


def add_library_path(db: Session, raw_path: str) -> list[str]:
    return _add_to_path_list(db, LIBRARY_PATHS_KEY, LIBRARY_PATH_KEY, raw_path)


def remove_library_path(db: Session, raw_path: str) -> list[str]:
    return _remove_from_path_list(db, LIBRARY_PATHS_KEY, LIBRARY_PATH_KEY, raw_path)


def update_library_path(db: Session, old_raw: str, new_raw: str) -> list[str]:
    return _update_in_path_list(
        db, LIBRARY_PATHS_KEY, LIBRARY_PATH_KEY, old_raw, new_raw
    )


# --- Папки архива проектов ---


def get_projects_path(db: Session) -> str | None:
    """Легаси: первый путь архива (для мест, которым нужен один). None — пусто."""
    paths = get_projects_paths(db)
    return paths[0] if paths else None


def get_projects_paths(db: Session) -> list[str]:
    """Список папок архива проектов (мигрирует со старого projects_library_path)."""
    return _get_path_list(db, PROJECTS_PATHS_KEY, PROJECTS_PATH_KEY)


def add_projects_path(db: Session, raw_path: str) -> list[str]:
    return _add_to_path_list(db, PROJECTS_PATHS_KEY, PROJECTS_PATH_KEY, raw_path)


def remove_projects_path(db: Session, raw_path: str) -> list[str]:
    return _remove_from_path_list(db, PROJECTS_PATHS_KEY, PROJECTS_PATH_KEY, raw_path)


def update_projects_path(db: Session, old_raw: str, new_raw: str) -> list[str]:
    return _update_in_path_list(
        db, PROJECTS_PATHS_KEY, PROJECTS_PATH_KEY, old_raw, new_raw
    )


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


def get_describe_images(db: Session) -> bool:
    """Включён ли vision при обработке (описание картинок). Дефолт — True (Стандарт)."""
    setting = db.scalar(select(Setting).where(Setting.key == DESCRIBE_IMAGES_KEY))
    return setting.value != "0" if setting else True


def set_describe_images(db: Session, enabled: bool) -> bool:
    """Сохраняет тумблер описания картинок. ВЫКЛ = режим «Без LLM» (бесплатно)."""
    value = "1" if enabled else "0"
    setting = db.scalar(select(Setting).where(Setting.key == DESCRIBE_IMAGES_KEY))
    if setting is None:
        db.add(Setting(key=DESCRIBE_IMAGES_KEY, value=value))
    else:
        setting.value = value
    db.commit()
    return enabled


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


def get_ui_language(db: Session) -> str:
    """Язык интерфейса/ошибок бэкенда. Дефолт — английский."""
    setting = db.scalar(select(Setting).where(Setting.key == UI_LANGUAGE_KEY))
    return setting.value if setting and setting.value in ui_messages.LANGS else "en"


def set_ui_language(db: Session, lang: str) -> str:
    """Сохраняет язык и сразу применяет его к текстам бэкенда.

    Бросает ValueError на неизвестный код (эндпоинт отдаст 400).
    """
    if lang not in ui_messages.LANGS:
        raise ValueError(f"Неизвестный язык: {lang}")
    setting = db.scalar(select(Setting).where(Setting.key == UI_LANGUAGE_KEY))
    if setting is None:
        db.add(Setting(key=UI_LANGUAGE_KEY, value=lang))
    else:
        setting.value = lang
    db.commit()
    ui_messages.set_language(lang)
    return lang


def apply_ui_language(db: Session) -> None:
    """Читает сохранённый язык и ставит его в ui_messages (вызов на старте)."""
    ui_messages.set_language(get_ui_language(db))


def get_answer_language(db: Session) -> str:
    """Язык ответа LLM (настройка в профиле). Дефолт — английский."""
    setting = db.scalar(select(Setting).where(Setting.key == ANSWER_LANGUAGE_KEY))
    return setting.value if setting and setting.value in ui_messages.LANGS else "en"


def set_answer_language(db: Session, lang: str) -> str:
    """Сохраняет язык ответа. Бросает ValueError на неизвестный код."""
    if lang not in ui_messages.LANGS:
        raise ValueError(f"Неизвестный язык: {lang}")
    setting = db.scalar(select(Setting).where(Setting.key == ANSWER_LANGUAGE_KEY))
    if setting is None:
        db.add(Setting(key=ANSWER_LANGUAGE_KEY, value=lang))
    else:
        setting.value = lang
    db.commit()
    return lang
