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
import os
import time
import uuid
from pathlib import Path

from jsonio import save_json_atomic

INDEX_DIR_NAME = ".search_index"
META_FILENAME = "meta.json"
# Поднимать при несовместимой смене формата артефактов — старые индексы
# перестанут «усыновляться» и будут переиндексированы.
FORMAT_VERSION = 1


def index_root(library_path: Path) -> Path:
    """Корень индексов папки библиотеки."""
    return library_path / INDEX_DIR_NAME


def same_dir(a: Path, b: Path) -> bool:
    """Один и тот же каталог на диске (симлинк / второй маунт)?

    Одну физическую папку, добавленную под двумя путями, нельзя считать
    двумя папками: скан регистрировал бы файлы дважды, кеш двоил бы чанки,
    а метка folder_id перевыдавалась бы «пинг-понгом» на каждый запрос.
    """
    try:
        return a.samefile(b)
    except OSError:
        return False


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

    Создание эксклюзивное (O_EXCL, как у lock-файла): когда две машины
    одновременно впервые открывают общую папку, паспорт записывает ровно
    одна, вторая читает победивший — иначе папка получила бы два folder_id
    и документы проигравшей метки осиротели бы.
    """
    meta = read_meta(library_path)
    if meta is not None:
        return meta
    meta = {
        "format_version": FORMAT_VERSION,
        "folder_id": uuid.uuid4().hex,
        "embedding_model": embedding_model,
    }
    if not library_path.is_dir():
        # Папку библиотеки НЕ создаём (принцип №16): её отсутствие — это
        # опечатка в пути или отвалившийся сетевой диск, маскировать нельзя.
        raise FileNotFoundError(f"Папка библиотеки недоступна: {library_path}")
    root = index_root(library_path)
    root.mkdir(exist_ok=True)
    try:
        fd = os.open(root / META_FILENAME, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return _wait_meta(library_path)  # проиграли гонку — читаем победителя
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    return meta


def _wait_meta(library_path: Path, attempts: int = 50, delay: float = 0.1) -> dict:
    """Читает meta.json с повторами: победитель гонки мог ещё не дописать файл.

    Не дождались валидного JSON — значит это не гонка, а битый файл. Молча
    перевыдавать id нельзя (осиротевшие документы, платная переиндексация
    всей папки), поэтому — громкая ошибка.
    """
    for _ in range(attempts):
        meta = read_meta(library_path)
        if meta is not None:
            return meta
        time.sleep(delay)
    raise OSError(
        "Битый паспорт папки (невалидный JSON): "
        f"{index_root(library_path) / META_FILENAME}"
    )


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


def resolve_folder(paths: list[Path], slug: str) -> Path | None:
    """Находит папку из списка, которой принадлежит документ (по метке в slug).

    slug = `{folder_id}__{файл}`; folder_id сверяем с meta.json каждой папки.
    None — папка отключена или slug легаси (без метки).
    """
    fid = folder_id_of(slug)
    if fid is None:
        return None
    for lib in paths:
        meta = read_meta(lib)
        if meta and meta.get("folder_id") == fid:
            return lib
    return None


def ensure_unique_folder_id(
    library_path: Path, taken: set[str], embedding_model: str
) -> str | None:
    """Метка папки, гарантированно не совпадающая с taken (уже занятыми).

    Если папку скопировали вместе со скрытой `.search_index` (meta.json тоже
    скопировался), у двух папок окажется одинаковый folder_id — метка должна
    быть уникальной, иначе документы одной папки полезут искать PDF в другой.
    В таком случае перевыдаём метку и переписываем meta.json.

    read-only папка без возможности записать meta.json → None (метку не
    выдать; такая папка не индексируется).
    """
    meta = read_meta(library_path)
    if meta is None:
        try:
            meta = ensure_meta(library_path, embedding_model)
        except OSError:
            return None
    fid = meta.get("folder_id")
    if not fid or fid in taken:
        fid = uuid.uuid4().hex
        meta["folder_id"] = fid
        try:
            save_json_atomic(index_root(library_path) / META_FILENAME, meta)
        except OSError:
            return None  # папка только для чтения — коллизию не починить
    return fid


def has_complete_index(library_path: Path, slug: str) -> bool:
    """Есть ли у документа полный ЧИТАЕМЫЙ индекс (нужный поиску минимум).

    chunks.json + embeddings.json достаточно: поиск читает только их,
    document.json/descriptions.json нужны лишь при переобработке.
    Оба файла обязаны разбираться как JSON: битый/недокопированный файл не
    «усыновляем» — иначе документ станет ready, а поиск его молча пропустит.
    Id чанков в обоих файлах обязаны совпадать: пара из разных поколений
    (крах/гонка между двумя сохранениями) роняла бы поиск KeyError'ом.
    """
    d = doc_dir(library_path, slug)
    try:
        with open(d / "chunks.json", encoding="utf-8") as f:
            chunks = json.load(f)
        with open(d / "embeddings.json", encoding="utf-8") as f:
            emb = json.load(f)
        if not chunks or "model" not in emb or "items" not in emb:
            return False
        chunk_ids = {c["chunk_id"] for c in chunks}
        item_ids = {item["chunk_id"] for item in emb["items"]}
    except (OSError, json.JSONDecodeError, TypeError, KeyError):
        return False
    return chunk_ids == item_ids
