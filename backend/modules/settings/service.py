"""Business logic of the settings module."""

import json
import os
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core import index_store, library_cache, secrets, ui_messages
from backend.core.ui_messages import msg
from backend.modules.documents.models import Document
from backend.modules.settings.models import Setting


LIBRARY_PATH_KEY = "library_path"  # legacy: single folder (migrated to the list)
# Library folder list (JSON). Replaced the single library_path: the user
# can attach several folders at once (own norms + a company folder).
LIBRARY_PATHS_KEY = "library_paths"
# The user's project-archive folders. Structure: {project}/.../file.pdf,
# project = the attached folder. See the projects module.
PROJECTS_PATH_KEY = "projects_library_path"  # legacy: single folder → list
PROJECTS_PATHS_KEY = "projects_library_paths"
# Vision model for document processing (the cost lever: vision is ~99% of
# a document's price). Default matches VISION_MODEL in
# pdf_processing/image_description.py.
VISION_MODEL_KEY = "vision_model"
VISION_MODELS = ("gpt-5.5", "gpt-5.4-mini")
DEFAULT_VISION_MODEL = "gpt-5.4-mini"  # cheaper; gpt-5.5 by choice in the UI
# Vision toggle: ON (default) = Standard (describe schemes and drawings),
# OFF = "No LLM" (OCR/text only, free). Stored as "1"/"0".
DESCRIBE_IMAGES_KEY = "describe_images"
OPENAI_KEY_KEY = "openai_api_key"
# Interface language (cs/en/de): the frontend sends it on switch, the
# backend uses it for error texts (backend/core/ui_messages.py).
UI_LANGUAGE_KEY = "ui_language"
# LLM ANSWER language (cs/en/de) — a profile setting, independent of the UI.
ANSWER_LANGUAGE_KEY = "answer_language"


def _validate_dir(raw_path: str) -> Path:
    """Normalize a user-entered path string into an absolute folder path.

    `~` and relative paths expand via expanduser+resolve. Raises
    ValueError when the path does not exist or is not a folder.
    """
    path = Path(raw_path).expanduser().resolve()
    if not path.exists():
        raise ValueError(msg("settings.path_not_found", path=path))
    if not path.is_dir():
        raise ValueError(msg("settings.not_a_dir", path=path))
    return path


def _set_path(db: Session, key: str, raw_path: str) -> str:
    """Validate and store a folder path under `key`."""
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
    """Current library folder path, or None when not set."""
    setting = db.scalar(select(Setting).where(Setting.key == LIBRARY_PATH_KEY))
    return setting.value if setting else None


def set_library_path(db: Session, raw_path: str) -> str:
    """Store the user's library folder path.

    Drops the search cache: indexes live in <folder>/.search_index, so a
    folder change changes the index pool too.
    """
    path = _set_path(db, LIBRARY_PATH_KEY, raw_path)
    library_cache.invalidate()
    return path


# --- Shared "folder list" mechanics (library and archive work alike) ---


def _get_path_list(db: Session, list_key: str, legacy_key: str | None) -> list[str]:
    """The folder list under list_key. Empty — nothing set.

    Migrates from the old single path under legacy_key: when the list
    does not exist yet but the legacy path does, it is moved over (once).
    """
    setting = db.scalar(select(Setting).where(Setting.key == list_key))
    if setting and setting.value:
        try:
            paths = json.loads(setting.value)
            if isinstance(paths, list):
                return [str(p) for p in paths]
        except (ValueError, TypeError):
            pass  # broken value — treat as "no list", try the migration

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
    """Add a folder (existence validated). Duplicates are idempotent."""
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
    """Remove a folder by normalized path. Indexes on disk stay."""
    target = str(Path(raw_path).expanduser().resolve())
    paths = [p for p in _get_path_list(db, list_key, legacy_key) if p != target]
    _save_path_list(db, list_key, paths)
    library_cache.invalidate()
    return paths


def _update_in_path_list(
    db: Session, list_key: str, legacy_key: str | None, old_raw: str, new_raw: str
) -> list[str]:
    """Edit a folder path in place (keeps position, dedupes)."""
    new_path = str(_validate_dir(new_raw))
    old_path = str(Path(old_raw).expanduser().resolve())

    result: list[str] = []
    seen: set[str] = set()
    replaced = False
    for p in _get_path_list(db, list_key, legacy_key):
        candidate = new_path if p == old_path else p
        if p == old_path:
            replaced = True
        if candidate not in seen:  # dedupe when `new` was already listed
            result.append(candidate)
            seen.add(candidate)
    if not replaced and new_path not in seen:
        result.append(new_path)

    _save_path_list(db, list_key, result)
    library_cache.invalidate()
    return result


# --- Norm library folders ---


def get_library_paths(db: Session) -> list[str]:
    """Library folder list (migrates from the old library_path)."""
    return _get_path_list(db, LIBRARY_PATHS_KEY, LIBRARY_PATH_KEY)


def add_library_path(db: Session, raw_path: str) -> list[str]:
    return _add_to_path_list(db, LIBRARY_PATHS_KEY, LIBRARY_PATH_KEY, raw_path)


def _forget_folder_documents(db: Session, raw_path: str) -> None:
    """Отвязка папки: удалить из БД записи её документов.

    Без этого документы отключённой папки повисают «сиротами» (файл не
    найден). Сам индекс в `.search_index` внутри папки не трогаем — при
    повторном подключении скан усыновит его бесплатно. Если папка
    недоступна и её ярлык не прочитать, не удаляем ничего: лучше сироты,
    чем снести документы чужой папки.
    """
    meta = index_store.read_meta(Path(raw_path).expanduser().resolve())
    folder_id = (meta or {}).get("folder_id")
    if not folder_id:
        return
    for doc in db.scalars(select(Document)).all():
        # processing не трогаем: пайплайн ещё пишет статус по этой записи.
        if doc.status == "processing":
            continue
        if index_store.folder_id_of(doc.slug) == folder_id:
            db.delete(doc)
    db.commit()


def remove_library_path(db: Session, raw_path: str) -> list[str]:
    _forget_folder_documents(db, raw_path)
    return _remove_from_path_list(db, LIBRARY_PATHS_KEY, LIBRARY_PATH_KEY, raw_path)


def update_library_path(db: Session, old_raw: str, new_raw: str) -> list[str]:
    return _update_in_path_list(
        db, LIBRARY_PATHS_KEY, LIBRARY_PATH_KEY, old_raw, new_raw
    )


# --- Project archive folders ---


def get_projects_path(db: Session) -> str | None:
    """Legacy: the first archive path (for callers that need one)."""
    paths = get_projects_paths(db)
    return paths[0] if paths else None


def get_projects_paths(db: Session) -> list[str]:
    """Archive folder list (migrates from the old projects_library_path)."""
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
    """Current vision model for processing; the default when unset."""
    setting = db.scalar(select(Setting).where(Setting.key == VISION_MODEL_KEY))
    return setting.value if setting else DEFAULT_VISION_MODEL


def set_vision_model(db: Session, model: str) -> str:
    """Store the vision-model choice. ValueError on an unknown model."""
    if model not in VISION_MODELS:
        raise ValueError(f"Unknown vision model: {model}")
    setting = db.scalar(select(Setting).where(Setting.key == VISION_MODEL_KEY))
    if setting is None:
        db.add(Setting(key=VISION_MODEL_KEY, value=model))
    else:
        setting.value = model
    db.commit()
    return model


def get_describe_images(db: Session) -> bool:
    """Is vision enabled during processing? Default True (Standard)."""
    setting = db.scalar(select(Setting).where(Setting.key == DESCRIBE_IMAGES_KEY))
    return setting.value != "0" if setting else True


def set_describe_images(db: Session, enabled: bool) -> bool:
    """Store the image-description toggle. OFF = "No LLM" mode (free)."""
    value = "1" if enabled else "0"
    setting = db.scalar(select(Setting).where(Setting.key == DESCRIBE_IMAGES_KEY))
    if setting is None:
        db.add(Setting(key=DESCRIBE_IMAGES_KEY, value=value))
    else:
        setting.value = value
    db.commit()
    return enabled


def get_openai_key(db: Session) -> str | None:
    """The stored OpenAI key, or None when not set (or unreadable).

    Unreadable happens when the DB was restored under a different Windows
    account: the key is protected per account (backend/core/secrets.py),
    and the user simply enters it again.
    """
    setting = db.scalar(select(Setting).where(Setting.key == OPENAI_KEY_KEY))
    return secrets.unprotect(setting.value) if setting else None


def set_openai_key(db: Session, raw_key: str) -> str:
    """Store the OpenAI key in the DB and put it into the environment.

    Checks the minimal format (`sk-...`). Writing to `os.environ` lets the
    very next `OpenAI()` call (search, indexing) pick up the new key
    without a restart — clients are created lazily inside functions.
    """
    key = raw_key.strip()
    if not key.startswith("sk-"):
        raise ValueError(msg("settings.bad_openai_key"))

    stored = secrets.protect(key)
    setting = db.scalar(select(Setting).where(Setting.key == OPENAI_KEY_KEY))
    if setting is None:
        setting = Setting(key=OPENAI_KEY_KEY, value=stored)
        db.add(setting)
    else:
        setting.value = stored
    db.commit()
    os.environ["OPENAI_API_KEY"] = key
    return key


def mask_key(key: str) -> str:
    """Mask the key for the frontend: only the last 4 characters show."""
    tail = key[-4:] if len(key) >= 4 else key
    return f"sk-…{tail}"


def apply_openai_key_to_env(db: Session) -> None:
    """At startup: put the DB key (when present) into the environment.

    The DB is the source of truth. Without a key the environment is left
    alone — the `.env` fallback stays (handy in development).

    Also the migration point: a key written before this build was stored
    plain, and the first start of the new version rewrites it protected.
    """
    setting = db.scalar(select(Setting).where(Setting.key == OPENAI_KEY_KEY))
    if setting is None:
        return
    key = secrets.unprotect(setting.value)
    if not key:
        return
    if secrets.needs_upgrade(setting.value):
        setting.value = secrets.protect(key)
        db.commit()
    os.environ["OPENAI_API_KEY"] = key


def get_ui_language(db: Session) -> str:
    """Interface/backend-error language. Default English."""
    setting = db.scalar(select(Setting).where(Setting.key == UI_LANGUAGE_KEY))
    return setting.value if setting and setting.value in ui_messages.LANGS else "en"


def set_ui_language(db: Session, lang: str) -> str:
    """Store the language and apply it to backend texts immediately.

    ValueError on an unknown code (the endpoint answers 400).
    """
    if lang not in ui_messages.LANGS:
        raise ValueError(f"Unknown language: {lang}")
    setting = db.scalar(select(Setting).where(Setting.key == UI_LANGUAGE_KEY))
    if setting is None:
        db.add(Setting(key=UI_LANGUAGE_KEY, value=lang))
    else:
        setting.value = lang
    db.commit()
    ui_messages.set_language(lang)
    return lang


def apply_ui_language(db: Session) -> None:
    """Read the stored language into ui_messages (called at startup)."""
    ui_messages.set_language(get_ui_language(db))


def get_answer_language(db: Session) -> str:
    """LLM answer language (profile setting). Default English."""
    setting = db.scalar(select(Setting).where(Setting.key == ANSWER_LANGUAGE_KEY))
    return setting.value if setting and setting.value in ui_messages.LANGS else "en"


def set_answer_language(db: Session, lang: str) -> str:
    """Store the answer language. ValueError on an unknown code."""
    if lang not in ui_messages.LANGS:
        raise ValueError(f"Unknown language: {lang}")
    setting = db.scalar(select(Setting).where(Setting.key == ANSWER_LANGUAGE_KEY))
    if setting is None:
        db.add(Setting(key=ANSWER_LANGUAGE_KEY, value=lang))
    else:
        setting.value = lang
    db.commit()
    return lang
