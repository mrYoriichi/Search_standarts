"""Backend messages for the UI in three languages (public version step 2.5).

The backend does not know each request's language: the frontend PUTs
/api/settings/language on switch, the value lives in settings and a module
global. Errors already written to the DB (error_message) keep the language
of the moment they happened — deliberately.
"""

import pytest

from backend.core import ui_messages
from backend.core.errors import classify_pipeline_error


@pytest.fixture(autouse=True)
def reset_language():
    """Each test starts from the default (English) and restores it."""
    ui_messages.set_language("en")
    yield
    ui_messages.set_language("en")


def _auth_error() -> Exception:
    return type("AuthenticationError", (Exception,), {})("401")


def test_default_language_is_english():
    assert "Invalid OpenAI API key" in classify_pipeline_error(_auth_error())


def test_czech_errors_after_switch():
    ui_messages.set_language("cs")
    assert "Neplatný OpenAI API klíč" in classify_pipeline_error(_auth_error())


def test_german_errors_after_switch():
    ui_messages.set_language("de")
    assert "Ungültiger OpenAI-API-Schlüssel" in classify_pipeline_error(_auth_error())


def test_unknown_language_is_ignored():
    ui_messages.set_language("fr")  # garbage must not break the texts
    assert ui_messages.get_language() == "en"


def test_every_key_has_all_three_languages():
    for key, entry in ui_messages.MESSAGES.items():
        assert set(entry) == {"cs", "en", "de"}, f"incomplete translation: {key}"


def test_params_are_substituted():
    ui_messages.set_language("en")
    text = ui_messages.msg("lib.folder_busy", owner="PC-KOLEGA")
    assert "PC-KOLEGA" in text
