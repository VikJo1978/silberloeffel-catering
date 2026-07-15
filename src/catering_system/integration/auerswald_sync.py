"""Read-only Auerswald missed-call sync client (separate service, not Core)."""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from urllib.parse import urlencode


def auth_header(user: str, password: str) -> str | None:
    if not user and not password:
        return None
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return f"Basic {token}"


def fetch_missed_board(
    url: str, user: str, password: str, limit: int = 100
) -> tuple[list[dict] | None, str | None]:
    if not url:
        return None, "AUERSWALD_SYNC_URL nicht konfiguriert"
    req = urllib.request.Request(f"{url.rstrip('/')}/missed-board.json?limit={limit}")
    auth = auth_header(user, password)
    if auth:
        req.add_header("Authorization", auth)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data.get("items", []), None
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        return None, str(exc)


def count_open_missed_calls(url: str, user: str, password: str) -> int:
    """Return open missed-call count; 0 when unconfigured or unreachable."""
    if not url:
        return 0
    items, error = fetch_missed_board(url, user, password)
    if error or not items:
        return 0
    return len(items)


class _NoRedirect(urllib.request.HTTPErrorProcessor):
    def http_response(self, request, response):
        return response

    https_response = http_response


def resolve_missed_call(url: str, user: str, password: str, call_id: str) -> None:
    req = urllib.request.Request(
        f"{url.rstrip('/')}/missed/resolve",
        data=urlencode({"call_id": call_id}).encode(),
        method="POST",
    )
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    auth = auth_header(user, password)
    if auth:
        req.add_header("Authorization", auth)
    opener = urllib.request.build_opener(_NoRedirect)
    with opener.open(req, timeout=5):
        pass
