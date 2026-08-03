"""Tests of atomic JSON writing (jsonio.save_json_atomic)."""

import json

from common.jsonio import save_json_atomic


def test_writes_valid_json_with_czech_chars(tmp_path):
    path = tmp_path / "data.json"
    save_json_atomic(path, {"název": "výztuž"})
    assert json.loads(path.read_text(encoding="utf-8")) == {"název": "výztuž"}
    # No temp file is left after a successful write.
    assert list(tmp_path.iterdir()) == [path]


def test_failed_write_keeps_old_file(tmp_path):
    # The point of atomicity: a failed write must not corrupt the old file.
    path = tmp_path / "data.json"
    save_json_atomic(path, {"a": 1})
    try:
        save_json_atomic(path, {"b": {1, 2}})  # a set is not JSON-serializable
    except TypeError:
        pass
    assert json.loads(path.read_text(encoding="utf-8")) == {"a": 1}
