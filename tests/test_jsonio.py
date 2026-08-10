"""Tests of atomic JSON writing (jsonio.save_json_atomic)."""

import json
import os

import pytest

from common import jsonio
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


def test_retries_replace_on_permission_error(tmp_path, monkeypatch):
    # OneDrive/антивирус держит файл пару секунд — os.replace кидает
    # PermissionError (WinError 5), но со 2–3 попытки проходит.
    path = tmp_path / "data.json"
    real_replace = os.replace
    calls = {"n": 0}

    def flaky_replace(src, dst):
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError(5, "Access is denied")
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", flaky_replace)
    monkeypatch.setattr(jsonio.time, "sleep", lambda s: None)
    save_json_atomic(path, {"a": 1})
    assert json.loads(path.read_text(encoding="utf-8")) == {"a": 1}
    assert list(tmp_path.iterdir()) == [path]  # tmp не остался


def test_gives_up_after_retries_and_cleans_tmp(tmp_path, monkeypatch):
    # Файл держат дольше всех попыток — ошибка пробрасывается, tmp подчищен.
    path = tmp_path / "data.json"

    def stuck_replace(src, dst):
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(os, "replace", stuck_replace)
    sleeps: list[float] = []
    monkeypatch.setattr(jsonio.time, "sleep", sleeps.append)
    with pytest.raises(PermissionError):
        save_json_atomic(path, {"a": 1})
    assert list(tmp_path.iterdir()) == []  # ни файла, ни tmp
    assert len(sleeps) == jsonio.REPLACE_ATTEMPTS - 1  # пауза между попытками
