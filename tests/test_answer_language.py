"""Язык ответа — выбор юзера (решение 2026-08-02, смягчение решения №12).

Чешский остаётся дефолтом; en/de подставляют своё имя языка в системный
промпт. Технические обозначения (коды норм, номера разделов) промпт
по-прежнему требует сохранять в оригинале.
"""

import pytest
from pydantic import ValidationError

from backend.modules.queries.schemas import AskRequest
from search.answer import build_system_prompt


def test_default_prompt_requires_czech():
    prompt = build_system_prompt()
    assert "ALWAYS answer in Czech" in prompt


def test_german_prompt_requires_german_not_czech():
    prompt = build_system_prompt("de")
    assert "ALWAYS answer in German" in prompt
    assert "ALWAYS answer in Czech" not in prompt


def test_english_prompt_requires_english():
    assert "ALWAYS answer in English" in build_system_prompt("en")


def test_unknown_language_falls_back_to_czech():
    # Защита от мусора в запросе: неизвестный код не должен ронять генерацию.
    assert "ALWAYS answer in Czech" in build_system_prompt("xx")


def test_ask_request_default_language_is_czech():
    req = AskRequest(question="jak se navrhuje most?")
    assert req.answer_language == "cs"


def test_ask_request_rejects_unknown_language():
    with pytest.raises(ValidationError):
        AskRequest(question="q", answer_language="fr")
