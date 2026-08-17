"""Update check against the latest GitHub release (fail-open).

Pins the contract: a newer release turns the banner on, anything else —
same version, network failure, unparseable tag — quietly means "no
update". Failures are not cached (retried on the next call), successes
are cached for the process lifetime.
"""

import httpx
import pytest

from backend.modules.health import update


RELEASE_URL = "https://github.com/mrYoriichi/mai-search/releases/tag/v9.9.9"


@pytest.fixture(autouse=True)
def fresh_cache(monkeypatch):
    """Each test starts with an empty process-lifetime cache."""
    monkeypatch.setattr(update, "_cache", None)


def _fake_get(payload: dict | None = None, status: int = 200):
    """Stub for httpx.get returning a canned GitHub answer (or a timeout)."""

    def fake_get(url, timeout, follow_redirects=False):
        if payload is None:
            raise httpx.ConnectTimeout("offline")
        return httpx.Response(status, json=payload, request=httpx.Request("GET", url))

    return fake_get


def test_newer_release_reports_update(monkeypatch):
    monkeypatch.setattr(
        update.httpx,
        "get",
        _fake_get({"tag_name": "v9.9.9", "html_url": RELEASE_URL}),
    )
    info = update.get_update_info()
    assert info == {
        "update_available": True,
        "latest_version": "9.9.9",
        "download_url": RELEASE_URL,
    }


@pytest.mark.parametrize("tag", ["v0.5.0", "v0.0.1", "beta", ""])
def test_same_old_or_broken_tag_means_no_update(monkeypatch, tag):
    monkeypatch.setattr(update, "APP_VERSION", "0.5.0")
    monkeypatch.setattr(
        update.httpx, "get", _fake_get({"tag_name": tag, "html_url": RELEASE_URL})
    )
    assert update.get_update_info()["update_available"] is False


def test_network_failure_means_no_update_and_no_caching(monkeypatch):
    monkeypatch.setattr(update.httpx, "get", _fake_get(payload=None))
    assert update.get_update_info()["update_available"] is False

    # The next call retries and sees the release.
    monkeypatch.setattr(
        update.httpx,
        "get",
        _fake_get({"tag_name": "v9.9.9", "html_url": RELEASE_URL}),
    )
    assert update.get_update_info()["update_available"] is True


def test_http_error_status_means_no_update(monkeypatch):
    monkeypatch.setattr(update.httpx, "get", _fake_get({}, status=403))
    assert update.get_update_info()["update_available"] is False


def test_success_is_cached(monkeypatch):
    calls = []

    def counting_get(url, timeout):
        calls.append(url)
        return httpx.Response(
            200,
            json={"tag_name": "v9.9.9", "html_url": RELEASE_URL},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(update.httpx, "get", counting_get)
    update.get_update_info()
    update.get_update_info()
    assert len(calls) == 1
