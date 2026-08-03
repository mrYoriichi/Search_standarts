"""Answer language is the user's choice (decision 2026-08-02, issue 12 closed).

Default is English (Maxim's decision 2026-08-02); cs/de substitute their
language name into the system prompt. Technical designations (standard
codes, section numbers) must still stay in the original per the prompt.
"""

import pytest
from pydantic import ValidationError

from backend.modules.queries.schemas import AskRequest
from search.answer import build_system_prompt


def test_default_prompt_requires_english():
    prompt = build_system_prompt()
    assert "ALWAYS answer in English" in prompt


def test_german_prompt_requires_german_not_czech():
    prompt = build_system_prompt("de")
    assert "ALWAYS answer in German" in prompt
    assert "ALWAYS answer in Czech" not in prompt


def test_czech_prompt_requires_czech():
    assert "ALWAYS answer in Czech" in build_system_prompt("cs")


def test_unknown_language_falls_back_to_english():
    # Guard against garbage in the request: an unknown code must not
    # break generation.
    assert "ALWAYS answer in English" in build_system_prompt("xx")


def test_ask_request_default_language_is_none():
    # None = "use the saved setting" (endpoint /api/settings/answer-language).
    req = AskRequest(question="jak se navrhuje most?")
    assert req.answer_language is None


def test_ask_request_rejects_unknown_language():
    with pytest.raises(ValidationError):
        AskRequest(question="q", answer_language="fr")


# --- answer_language setting (stored in the profile) -------------------------


@pytest.fixture
def db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from backend.core.database import Base

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def test_answer_language_setting_defaults_to_english(db):
    from backend.modules.settings import service

    assert service.get_answer_language(db) == "en"


def test_answer_language_setting_roundtrip(db):
    from backend.modules.settings import service

    service.set_answer_language(db, "de")
    assert service.get_answer_language(db) == "de"


def test_answer_language_setting_rejects_unknown(db):
    from backend.modules.settings import service

    with pytest.raises(ValueError):
        service.set_answer_language(db, "fr")
