"""Update check: compare APP_VERSION with the latest GitHub release.

Fail-open by design: any network or parsing problem means "no update" —
the app must never break because GitHub is unreachable. A successful
answer is cached for the process lifetime (the app restarts daily anyway,
and GitHub allows only 60 anonymous API calls per hour).
"""

import httpx

from backend.version import APP_VERSION

RELEASES_URL = "https://api.github.com/repos/mrYoriichi/mai-search/releases/latest"

_NO_UPDATE: dict = {
    "update_available": False,
    "latest_version": None,
    "download_url": None,
}

_cache: dict | None = None


def _parse_version(version: str) -> tuple[int, ...] | None:
    """'0.5.0' -> (0, 5, 0); None when the string is not X.Y.Z numbers."""
    try:
        return tuple(int(part) for part in version.split("."))
    except ValueError:
        return None


def get_update_info() -> dict:
    """Return update info, hitting GitHub only until the first success."""
    global _cache
    if _cache is None:
        _cache = _fetch_update_info()
    return _cache or _NO_UPDATE


def _fetch_update_info() -> dict | None:
    """One GitHub call; None (= retry next time) on any failure."""
    try:
        # follow_redirects: httpx сам по редиректам не ходит, а GitHub
        # отвечает 301 после переименования репозитория — без этого
        # флага проверка обновлений молча умерла бы при каждом rename.
        response = httpx.get(RELEASES_URL, timeout=5, follow_redirects=True)
        response.raise_for_status()
        release = response.json()
    except (httpx.HTTPError, ValueError):
        return None

    latest = str(release.get("tag_name", "")).removeprefix("v")
    latest_parsed = _parse_version(latest)
    current_parsed = _parse_version(APP_VERSION)
    if latest_parsed is None or current_parsed is None:
        return None
    if latest_parsed <= current_parsed:
        return _NO_UPDATE
    return {
        "update_available": True,
        "latest_version": latest,
        "download_url": release.get("html_url"),
    }
