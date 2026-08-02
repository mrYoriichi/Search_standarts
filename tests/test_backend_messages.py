"""Серверные сообщения для UI на трёх языках (шаг 2.5 публичной версии).

Бэкенд не знает язык каждого запроса: фронт при переключении шлёт
PUT /api/settings/language, значение живёт в settings и module-global.
Уже записанные в БД ошибки (error_message) остаются на языке момента
падения — осознанно.
"""

import pytest

from backend.core import ui_messages
from backend.core.errors import classify_pipeline_error


@pytest.fixture(autouse=True)
def reset_language():
    """Каждый тест стартует с чешского и возвращает его после себя."""
    ui_messages.set_language("cs")
    yield
    ui_messages.set_language("cs")


def _auth_error() -> Exception:
    return type("AuthenticationError", (Exception,), {})("401")


def test_default_language_is_czech():
    assert "Neplatný OpenAI API klíč" in classify_pipeline_error(_auth_error())


def test_english_errors_after_switch():
    ui_messages.set_language("en")
    assert "Invalid OpenAI API key" in classify_pipeline_error(_auth_error())


def test_german_errors_after_switch():
    ui_messages.set_language("de")
    assert "Ungültiger OpenAI-API-Schlüssel" in classify_pipeline_error(_auth_error())


def test_unknown_language_is_ignored():
    ui_messages.set_language("fr")  # мусор не должен ломать тексты
    assert ui_messages.get_language() == "cs"


def test_every_key_has_all_three_languages():
    for key, entry in ui_messages.MESSAGES.items():
        assert set(entry) == {"cs", "en", "de"}, f"неполный перевод: {key}"


def test_params_are_substituted():
    ui_messages.set_language("en")
    text = ui_messages.msg("lib.folder_busy", owner="PC-KOLEGA")
    assert "PC-KOLEGA" in text
