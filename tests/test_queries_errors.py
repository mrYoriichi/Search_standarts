"""OpenAI errors in /api/queries must arrive as readable text, not HTTP 500.

The router caught only RuntimeError, while all OpenAI SDK errors inherit
from Exception: a bad key, a network drop or an exhausted quota turned into
a faceless "Server vrátil 500" on the frontend.
"""

import httpx
import openai
import pytest

from backend.core import ui_messages
from fastapi import HTTPException

from backend.modules.queries import router as queries_router
from backend.modules.queries.schemas import AskRequest


@pytest.fixture(autouse=True)
def czech_messages():
    """Test texts are the Czech references; the app default is English now."""
    ui_messages.set_language("cs")
    yield
    ui_messages.set_language("en")


def _raise_from_ask(monkeypatch, exc: Exception) -> None:
    def boom(**kwargs):
        raise exc

    monkeypatch.setattr(queries_router.service, "ask", boom)


def _create_query() -> None:
    queries_router.create_query(AskRequest(question="Jaká je krycí vrstva?"), db=None)


def test_bad_api_key_becomes_readable_502(monkeypatch):
    _raise_from_ask(
        monkeypatch,
        openai.AuthenticationError(
            "Incorrect API key provided",
            response=httpx.Response(
                401, request=httpx.Request("POST", "https://api.openai.com/v1")
            ),
            body=None,
        ),
    )
    with pytest.raises(HTTPException) as err:
        _create_query()
    assert err.value.status_code == 502
    assert "klíč" in err.value.detail


def test_missing_api_key_becomes_readable_502(monkeypatch):
    # A fresh install: no key entered yet, the OpenAI client fails on creation.
    _raise_from_ask(
        monkeypatch, openai.OpenAIError("The api_key client option must be set")
    )
    with pytest.raises(HTTPException) as err:
        _create_query()
    assert err.value.status_code == 502
    assert "Chybí OpenAI API klíč" in err.value.detail
