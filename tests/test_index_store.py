"""Тесты хранилища индексов .search_index в папке библиотеки."""

import json

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


def test_ensure_meta_keeps_existing(tmp_path):
    first = index_store.ensure_meta(tmp_path, "text-embedding-3-large")
    # Повторный вызов (даже с другой моделью) НЕ трогает паспорт папки:
    # id постоянный, конфликт модели решает вызывающий код.
    second = index_store.ensure_meta(tmp_path, "other-model")
    assert second == first


def test_has_complete_index(tmp_path):
    slug = "mvl_649"
    assert not index_store.has_complete_index(tmp_path, slug)
    d = index_store.doc_dir(tmp_path, slug)
    d.mkdir(parents=True)
    (d / "chunks.json").write_text("[]", encoding="utf-8")
    assert not index_store.has_complete_index(tmp_path, slug)
    (d / "embeddings.json").write_text("{}", encoding="utf-8")
    assert index_store.has_complete_index(tmp_path, slug)
