"""Strictly opt-in (off by default) SteamGridDB cover art fetcher.

This is the ONLY module in GameRewind allowed to make outbound HTTPS requests,
and it does nothing unless both ``enabled=True`` and a non-empty user-supplied
``api_key`` are explicitly provided. The API key is never logged.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable

_API_BASE = "https://www.steamgriddb.com/api/v2"
_ALLOWED_API_HOSTS: frozenset[str] = frozenset({"www.steamgriddb.com"})
_ALLOWED_CDN_HOSTS: frozenset[str] = frozenset({"cdn.steamgriddb.com", "cdn2.steamgriddb.com"})
_REQUEST_TIMEOUT_SEC = 6.0
_MAX_JSON_BYTES = 256 * 1024
_MAX_IMAGE_BYTES = 8 * 1024 * 1024
_LANDSCAPE_DIMS = "460x215,920x430"


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(
            req.full_url, code, "Redirects are disabled for security.", headers, fp
        )


def _validate_https_host(url: str, allowed_hosts: frozenset[str]) -> None:
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or host not in allowed_hosts:
        raise ValueError(f"Disallowed HTTPS host: {host!r}")


def _default_get_bytes(url: str, headers: dict[str, str], max_bytes: int) -> bytes:
    _validate_https_host(url, _ALLOWED_API_HOSTS | _ALLOWED_CDN_HOSTS)
    opener = urllib.request.build_opener(_NoRedirectHandler())
    req = urllib.request.Request(url, headers=headers, method="GET")
    with opener.open(req, timeout=_REQUEST_TIMEOUT_SEC) as resp:
        data = resp.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError("Response exceeded maximum allowed size.")
    return data


def _extract_grid_url(payload: object) -> str | None:
    if not isinstance(payload, dict) or not payload.get("success"):
        return None
    items = payload.get("data")
    if not isinstance(items, list):
        return None
    for item in items:
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        if isinstance(url, str):
            parsed = urllib.parse.urlparse(url)
            if parsed.scheme == "https" and (parsed.hostname or "").lower() in _ALLOWED_CDN_HOSTS:
                return url
    return None


def fetch_steamgriddb_cover(
    game_name: str,
    *,
    enabled: bool,
    api_key: str,
    http_get: Callable[[str, dict[str, str], int], bytes] | None = None,
) -> bytes | None:
    """Fetch wide cover art bytes for ``game_name`` if and only if opted in with an API key."""
    key = api_key.strip()
    query = game_name.strip()
    if not enabled or not key or not query:
        return None

    getter = http_get if http_get is not None else _default_get_bytes
    headers = {
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
        "User-Agent": "GameRewind/1.2",
    }

    try:
        search_url = f"{_API_BASE}/search/autocomplete/{urllib.parse.quote(query, safe='')}"
        search_payload = json.loads(getter(search_url, headers, _MAX_JSON_BYTES).decode("utf-8"))
        if not isinstance(search_payload, dict) or not search_payload.get("success"):
            return None
        matches = search_payload.get("data")
        if not isinstance(matches, list) or not matches or not isinstance(matches[0], dict):
            return None
        sgdb_id = matches[0].get("id")
        if not isinstance(sgdb_id, int):
            return None

        # Prefer wide landscape grids matching the 16:9 library card proportion.
        wide_url = f"{_API_BASE}/grids/game/{sgdb_id}?dimensions={_LANDSCAPE_DIMS}"
        grid_payload = json.loads(getter(wide_url, headers, _MAX_JSON_BYTES).decode("utf-8"))
        image_url = _extract_grid_url(grid_payload)
        if image_url is None:
            fallback_url = f"{_API_BASE}/grids/game/{sgdb_id}"
            fallback_payload = json.loads(
                getter(fallback_url, headers, _MAX_JSON_BYTES).decode("utf-8")
            )
            image_url = _extract_grid_url(fallback_payload)
        if image_url is None:
            return None

        image_headers = {"User-Agent": "GameRewind/1.2"}
        return getter(image_url, image_headers, _MAX_IMAGE_BYTES)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, TypeError):
        return None
