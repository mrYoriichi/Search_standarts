"""Тесты атомарной записи JSON (jsonio.save_json_atomic)."""

import json

from jsonio import save_json_atomic


def test_writes_valid_json_with_czech_chars(tmp_path):
    path = tmp_path / "data.json"
    save_json_atomic(path, {"název": "výztuž"})
    assert json.loads(path.read_text(encoding="utf-8")) == {"název": "výztuž"}
    # Временный файл после успешной записи не остаётся.
    assert list(tmp_path.iterdir()) == [path]


def test_failed_write_keeps_old_file(tmp_path):
    # Смысл атомарности: упавшая запись не должна портить старый файл.
    path = tmp_path / "data.json"
    save_json_atomic(path, {"a": 1})
    try:
        save_json_atomic(path, {"b": {1, 2}})  # set не сериализуется в JSON
    except TypeError:
        pass
    assert json.loads(path.read_text(encoding="utf-8")) == {"a": 1}
