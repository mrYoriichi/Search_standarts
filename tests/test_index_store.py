"""Тесты хранилища индексов .search_index в папке библиотеки."""

import json

import pytest

from backend.core import index_store


def test_doc_dir_inside_search_index(tmp_path):
    d = index_store.doc_dir(tmp_path, "mvl_649")
    assert d == tmp_path / ".search_index" / "mvl_649"


def test_read_meta_absent(tmp_path):
    assert index_store.read_meta(tmp_path) is None


def test_read_meta_broken_json(tmp_path):
    root = tmp_path / ".search_index"
    root.mkdir()
    (root / "meta.json").write_text("{oops", encoding="utf-8")
    assert index_store.read_meta(tmp_path) is None


def test_ensure_meta_creates_passport(tmp_path):
    meta = index_store.ensure_meta(tmp_path, "text-embedding-3-large")
    assert meta["embedding_model"] == "text-embedding-3-large"
    assert meta["format_version"] == index_store.FORMAT_VERSION
    assert meta["folder_id"]
    # Файл реально лежит на диске и читается обратно.
    on_disk = json.loads(
        (tmp_path / ".search_index" / "meta.json").read_text(encoding="utf-8")
    )
    assert on_disk == meta


def test_ensure_meta_missing_folder_raises(tmp_path):
    # Папку библиотеки НЕ создаём (принцип №16): её отсутствие — опечатка в
    # пути или отвалившийся сетевой диск, маскировать нельзя.
    missing = tmp_path / "neexistuje"
    with pytest.raises(OSError):
        index_store.ensure_meta(missing, "text-embedding-3-large")
    assert not missing.exists()


def test_ensure_unique_folder_id_missing_folder_is_none(tmp_path):
    missing = tmp_path / "neexistuje"
    assert index_store.ensure_unique_folder_id(missing, set(), "m") is None


def test_ensure_meta_keeps_existing(tmp_path):
    first = index_store.ensure_meta(tmp_path, "text-embedding-3-large")
    # Повторный вызов (даже с другой моделью) НЕ трогает паспорт папки:
    # id постоянный, конфликт модели решает вызывающий код.
    second = index_store.ensure_meta(tmp_path, "other-model")
    assert second == first


def test_scoped_slug_roundtrip():
    slug = index_store.scoped_slug("abc123", "most_2025")
    assert slug == "abc123__most_2025"
    assert index_store.folder_id_of(slug) == "abc123"


def test_scoped_slug_keeps_underscores_in_filename():
    # Имя файла с '__' не должно ломать разбор — метку берём до ПЕРВОГО '__'.
    slug = index_store.scoped_slug("abc123", "so_211__tz")
    assert index_store.folder_id_of(slug) == "abc123"


def test_folder_id_of_legacy_slug_is_none():
    # Старый slug без метки папки — метки нет.
    assert index_store.folder_id_of("mvl_649") is None


def test_has_complete_index(tmp_path):
    slug = "mvl_649"
    assert not index_store.has_complete_index(tmp_path, slug)
    d = index_store.doc_dir(tmp_path, slug)
    d.mkdir(parents=True)
    (d / "chunks.json").write_text('[{"chunk_id": "mvl_649_c001"}]', encoding="utf-8")
    assert not index_store.has_complete_index(tmp_path, slug)  # нет embeddings
    (d / "embeddings.json").write_text(
        '{"model": "text-embedding-3-large",'
        ' "items": [{"chunk_id": "mvl_649_c001", "embedding": [0.1]}]}',
        encoding="utf-8",
    )
    assert index_store.has_complete_index(tmp_path, slug)


def test_has_complete_index_rejects_id_mismatch(tmp_path):
    # chunks.json и embeddings.json из разных поколений (крах/гонка между
    # двумя сохранениями): усыновив такую пару, поиск падал бы KeyError'ом.
    slug = "mvl_649"
    d = index_store.doc_dir(tmp_path, slug)
    d.mkdir(parents=True)
    (d / "chunks.json").write_text('[{"chunk_id": "mvl_649_c001"}]', encoding="utf-8")
    (d / "embeddings.json").write_text(
        '{"model": "x", "items": [{"chunk_id": "mvl_649_c999", "embedding": [0.1]}]}',
        encoding="utf-8",
    )
    assert not index_store.has_complete_index(tmp_path, slug)
    # Вектора нет вовсе (embeddings отстал) — тоже не полный индекс.
    (d / "embeddings.json").write_text('{"model": "x", "items": []}', encoding="utf-8")
    assert not index_store.has_complete_index(tmp_path, slug)


def test_has_complete_index_rejects_broken_json(tmp_path):
    # Оборванный при копировании/записи файл не «усыновляем» — иначе документ
    # станет ready, а поиск его молча пропустит.
    slug = "mvl_649"
    d = index_store.doc_dir(tmp_path, slug)
    d.mkdir(parents=True)
    (d / "chunks.json").write_text('[{"chunk_id": "mvl_649_c001"}]', encoding="utf-8")
    (d / "embeddings.json").write_text('{"model": "x", "items": [', encoding="utf-8")
    assert not index_store.has_complete_index(tmp_path, slug)


def test_has_complete_index_rejects_empty_chunks(tmp_path):
    slug = "mvl_649"
    d = index_store.doc_dir(tmp_path, slug)
    d.mkdir(parents=True)
    (d / "chunks.json").write_text("[]", encoding="utf-8")
    (d / "embeddings.json").write_text('{"model": "x", "items": []}', encoding="utf-8")
    assert not index_store.has_complete_index(tmp_path, slug)
