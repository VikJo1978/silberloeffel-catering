"""Staging website for developing and exercising the public inquiry form.

By default submissions stay in the VPS SQLite database. When the paired
server-side Core intake URL and token are configured, validated test
submissions are forwarded through the narrow website-intake contract before a
local audit copy is stored. The browser never receives the token or Core URL.
"""

from __future__ import annotations

import argparse
import html
import ipaddress
import json
import os
import re
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections import defaultdict, deque
from datetime import date, datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

_ASSET_DIR = Path(__file__).with_name("staging_site_assets")
_MAX_BODY_BYTES = 16 * 1024
_RATE_LIMIT_COUNT = 8
_RATE_LIMIT_WINDOW_SECONDS = 60.0
_CORE_RESPONSE_LIMIT = 8 * 1024
_CORE_ROUTE = "/intake/website-form"
_SUBMISSION_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,120}")

_CORE_PAYLOAD_FIELDS = (
    "event_date",
    "time_window_text",
    "location_text",
    "guest_count_estimate",
    "company",
    "name",
    "email",
    "phone",
    "event_type",
    "message",
    "submission_id",
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS staging_inquiries (
    submission_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    event_date TEXT NOT NULL,
    time_window_text TEXT NOT NULL,
    location_text TEXT NOT NULL,
    guest_count_estimate INTEGER,
    company TEXT NOT NULL,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    phone TEXT NOT NULL,
    event_type TEXT NOT NULL,
    message TEXT NOT NULL
)
"""

_TEXT_LIMITS = {
    "time_window_text": 500,
    "location_text": 500,
    "company": 500,
    "name": 500,
    "email": 500,
    "phone": 500,
    "event_type": 500,
    "message": 5000,
}

_INQUIRY_COLUMNS = (
    "submission_id",
    "created_at",
    "event_date",
    "time_window_text",
    "location_text",
    "guest_count_estimate",
    "company",
    "name",
    "email",
    "phone",
    "event_type",
    "message",
)


class StagingInquiryRepository:
    def __init__(self, db_path: str | Path) -> None:
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        with self._connection:
            self._connection.execute(_SCHEMA)

    def close(self) -> None:
        self._connection.close()

    def save(self, inquiry: dict[str, Any]) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT OR IGNORE INTO staging_inquiries VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    inquiry["submission_id"],
                    inquiry["created_at"],
                    inquiry["event_date"],
                    inquiry["time_window_text"],
                    inquiry["location_text"],
                    inquiry["guest_count_estimate"],
                    inquiry["company"],
                    inquiry["name"],
                    inquiry["email"],
                    inquiry["phone"],
                    inquiry["event_type"],
                    inquiry["message"],
                ),
            )

    def list_recent(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM staging_inquiries ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(zip(_INQUIRY_COLUMNS, row, strict=True)) for row in rows]


class SubmissionRateLimiter:
    """Small in-memory limiter for an exposed staging form."""

    def __init__(
        self,
        limit: int = _RATE_LIMIT_COUNT,
        window_seconds: float = _RATE_LIMIT_WINDOW_SECONDS,
    ) -> None:
        self._limit = limit
        self._window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, client: str, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else now
        cutoff = current - self._window_seconds
        with self._lock:
            hits = self._hits[client]
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= self._limit:
                return False
            hits.append(current)
            return True


class CoreIntakeForwardError(RuntimeError):
    """The narrow Core receiver did not confirm the submission."""


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: object, **kwargs: object) -> None:
        return None


def validate_core_intake_url(raw_url: str) -> str:
    """Require the SSH-forwarded Core receiver to remain on loopback."""
    try:
        parsed = urllib.parse.urlsplit(raw_url)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Core intake URL is invalid") from exc
    if (
        parsed.scheme != "http"
        or parsed.hostname is None
        or not ipaddress.ip_address(parsed.hostname).is_loopback
        or parsed.username is not None
        or parsed.password is not None
        or port is None
        or parsed.path != _CORE_ROUTE
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            f"Core intake URL must be an exact loopback HTTP URL for {_CORE_ROUTE}"
        )
    return raw_url


class CoreIntakeClient:
    def __init__(self, url: str, token: str, timeout_seconds: float = 3.0) -> None:
        self._url = validate_core_intake_url(url)
        if not token:
            raise ValueError("Core intake token must not be empty")
        self._token = token
        self._timeout_seconds = timeout_seconds

    def forward(self, inquiry: dict[str, Any]) -> None:
        payload = {field: inquiry[field] for field in _CORE_PAYLOAD_FIELDS}
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self._url,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
            },
        )
        opener = urllib.request.build_opener(_NoRedirectHandler())
        try:
            with opener.open(request, timeout=self._timeout_seconds) as response:
                if response.status != 202:
                    raise CoreIntakeForwardError("Core intake did not accept request")
                raw = response.read(_CORE_RESPONSE_LIMIT + 1)
        except CoreIntakeForwardError:
            raise
        except (OSError, TimeoutError, urllib.error.URLError) as exc:
            raise CoreIntakeForwardError("Core intake unavailable") from exc
        if len(raw) > _CORE_RESPONSE_LIMIT:
            raise CoreIntakeForwardError("Core intake response is too large")
        try:
            result = json.loads(raw)
        except (UnicodeDecodeError, ValueError) as exc:
            raise CoreIntakeForwardError("Core intake returned invalid JSON") from exc
        if (
            not isinstance(result, dict)
            or result.get("accepted") is not True
            or not isinstance(result.get("inquiry_id"), str)
            or not result["inquiry_id"]
        ):
            raise CoreIntakeForwardError("Core intake returned an invalid response")


def _text(payload: dict[str, Any], field: str, *, required: bool = False) -> str:
    raw = payload.get(field, "")
    if not isinstance(raw, str):
        raise ValueError(f"{field} must be text")
    value = raw.strip()
    if required and not value:
        raise ValueError(f"{field} is required")
    if len(value) > _TEXT_LIMITS[field]:
        raise ValueError(f"{field} is too long")
    return value


def _submission_id(payload: dict[str, Any]) -> str:
    raw = payload.get("submission_id")
    if raw in (None, ""):
        value = str(uuid.uuid4())
    elif isinstance(raw, str) and _SUBMISSION_ID_RE.fullmatch(raw):
        value = raw
    else:
        raise ValueError("submission_id is invalid")
    return f"vps-staging-{value}"


def validate_staging_payload(payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    if payload.get("website"):
        raise ValueError("submission rejected")

    event_date = payload.get("event_date")
    if not isinstance(event_date, str):
        raise ValueError("event_date is required")
    try:
        parsed_date = date.fromisoformat(event_date)
    except ValueError as exc:
        raise ValueError("event_date must be a valid ISO date") from exc

    name = _text(payload, "name", required=True)
    email = _text(payload, "email")
    phone = _text(payload, "phone")
    if not email and not phone:
        raise ValueError("email or phone is required")
    if email and ("@" not in email or email.startswith("@") or email.endswith("@")):
        raise ValueError("email is invalid")

    guests_raw = payload.get("guest_count_estimate")
    if guests_raw in (None, ""):
        guest_count: int | None = None
    elif isinstance(guests_raw, bool):
        raise ValueError("guest_count_estimate must be an integer")
    elif isinstance(guests_raw, int):
        guest_count = guests_raw
    elif isinstance(guests_raw, str):
        try:
            guest_count = int(guests_raw)
        except ValueError as exc:
            raise ValueError("guest_count_estimate must be an integer") from exc
    else:
        raise ValueError("guest_count_estimate must be an integer")
    if guest_count is not None and (guest_count < 1 or guest_count > 2000):
        raise ValueError("guest_count_estimate must be between 1 and 2000")

    return {
        "submission_id": _submission_id(payload),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "event_date": parsed_date.isoformat(),
        "time_window_text": _text(payload, "time_window_text"),
        "location_text": _text(payload, "location_text"),
        "guest_count_estimate": guest_count,
        "company": _text(payload, "company"),
        "name": name,
        "email": email,
        "phone": phone,
        "event_type": _text(payload, "event_type"),
        "message": _text(payload, "message"),
    }


def is_loopback_client(address: str) -> bool:
    try:
        return ipaddress.ip_address(address).is_loopback
    except ValueError:
        return False


def render_staging_admin(inquiries: list[dict[str, Any]]) -> bytes:
    def value(inquiry: dict[str, Any], field: str, fallback: str = "—") -> str:
        raw = inquiry.get(field)
        return html.escape(str(raw)) if raw not in (None, "") else fallback

    cards = "".join(
        f"""
        <article class="admin-card">
          <div class="admin-card-heading">
            <div><strong>{value(inquiry, "event_date")}</strong>
              <span>{value(inquiry, "event_type", "Testanfrage")}</span></div>
            <code>{value(inquiry, "submission_id")[:8]}</code>
          </div>
          <dl>
            <div><dt>Name</dt><dd>{value(inquiry, "name")}</dd></div>
            <div><dt>Firma</dt><dd>{value(inquiry, "company")}</dd></div>
            <div><dt>Kontakt</dt><dd>{value(inquiry, "email")} · {value(inquiry, "phone")}</dd></div>
            <div><dt>Ort / Zeit</dt><dd>{value(inquiry, "location_text")} · {value(inquiry, "time_window_text")}</dd></div>
            <div><dt>Gäste</dt><dd>{value(inquiry, "guest_count_estimate")}</dd></div>
            <div><dt>Gespeichert</dt><dd>{value(inquiry, "created_at")}</dd></div>
          </dl>
          <p>{value(inquiry, "message", "Keine Wünsche angegeben.")}</p>
        </article>
        """
        for inquiry in inquiries
    )
    if not cards:
        cards = '<p class="admin-empty">Noch keine Testanfragen gespeichert.</p>'
    page = f"""<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Silberlöffel — Staging-Anfragen</title>
  <link rel="stylesheet" href="/styles.css">
</head>
<body class="admin-body">
  <main class="admin-shell">
    <p class="step">Nur über SSH-Tunnel erreichbar</p>
    <h1>Staging-Anfragen</h1>
    <p class="admin-intro">Die letzten {len(inquiries)} Testanfragen aus der isolierten VPS-Datenbank.</p>
    <section class="admin-list">{cards}</section>
  </main>
</body>
</html>"""
    return page.encode("utf-8")


def make_staging_handler(
    repository: StagingInquiryRepository,
    rate_limiter: SubmissionRateLimiter | None = None,
    core_intake_client: CoreIntakeClient | None = None,
) -> type[BaseHTTPRequestHandler]:
    limiter = rate_limiter or SubmissionRateLimiter()

    class StagingHandler(BaseHTTPRequestHandler):
        server_version = "CateringStaging/1.0"

        def end_headers(self) -> None:
            self.send_header("Cache-Control", "no-store")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; style-src 'self'; script-src 'self'; "
                "connect-src 'self'; img-src 'self' data:; form-action 'self'; "
                "base-uri 'none'; frame-ancestors 'none'",
            )
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            super().end_headers()

        def _send(self, status: int, content_type: str, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, payload: object) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self._send(status, "application/json; charset=utf-8", body)

        def _asset(self, name: str, content_type: str) -> None:
            try:
                body = (_ASSET_DIR / name).read_bytes()
            except OSError:
                self.send_error(500)
                return
            self._send(200, content_type, body)

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/":
                self._asset("index.html", "text/html; charset=utf-8")
            elif self.path == "/styles.css":
                self._asset("styles.css", "text/css; charset=utf-8")
            elif self.path == "/app.js":
                self._asset("app.js", "text/javascript; charset=utf-8")
            elif self.path == "/healthz":
                self._json(
                    200,
                    {
                        "status": "ok",
                        "environment": "staging",
                        "core_forwarding": core_intake_client is not None,
                    },
                )
            elif self.path == "/admin":
                if not is_loopback_client(self.client_address[0]):
                    self.send_error(404)
                    return
                self._send(
                    200,
                    "text/html; charset=utf-8",
                    render_staging_admin(repository.list_recent()),
                )
            else:
                self.send_error(404)

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/api/inquiries":
                self.send_error(404)
                return
            if not self.headers.get("Content-Type", "").startswith("application/json"):
                self._json(415, {"error": "unsupported content type"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self._json(400, {"error": "invalid content length"})
                return
            if length < 0:
                self._json(400, {"error": "invalid content length"})
                return
            if length > _MAX_BODY_BYTES:
                self._json(413, {"error": "payload too large"})
                return
            if not limiter.allow(self.client_address[0]):
                self._json(429, {"error": "too many requests"})
                return
            try:
                payload = json.loads(self.rfile.read(length))
                inquiry = validate_staging_payload(payload)
            except (ValueError, UnicodeDecodeError) as exc:
                self._json(400, {"error": str(exc)})
                return
            if core_intake_client is not None:
                try:
                    core_intake_client.forward(inquiry)
                except CoreIntakeForwardError:
                    self._json(502, {"error": "Core intake temporarily unavailable"})
                    return
            repository.save(inquiry)
            self._json(
                202 if core_intake_client is not None else 201,
                {
                    "accepted": True,
                    "environment": "staging",
                    "submission_id": inquiry["submission_id"],
                    "forwarded_to_core": core_intake_client is not None,
                },
            )

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            pass

    return StagingHandler


class StagingHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        db_path: str | Path,
        core_intake_client: CoreIntakeClient | None = None,
    ) -> None:
        self.repository = StagingInquiryRepository(db_path)
        super().__init__(
            address,
            make_staging_handler(
                self.repository, core_intake_client=core_intake_client
            ),
        )

    def server_close(self) -> None:
        super().server_close()
        self.repository.close()


def create_staging_server(
    db_path: str | Path,
    host: str = "127.0.0.1",
    port: int = 8080,
    core_intake_client: CoreIntakeClient | None = None,
) -> StagingHTTPServer:
    return StagingHTTPServer((host, port), db_path, core_intake_client)


def main() -> None:
    parser = argparse.ArgumentParser(description="Catering inquiry-form staging site")
    parser.add_argument("--db", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    core_url = os.environ.get("STAGING_CORE_INTAKE_URL", "").strip()
    core_token = os.environ.get("STAGING_CORE_INTAKE_TOKEN", "")
    if bool(core_url) != bool(core_token):
        raise SystemExit(
            "STAGING_CORE_INTAKE_URL and STAGING_CORE_INTAKE_TOKEN must be "
            "configured together"
        )
    core_client = CoreIntakeClient(core_url, core_token) if core_url else None
    server = create_staging_server(
        args.db, args.host, args.port, core_intake_client=core_client
    )
    print(f"Catering staging site on http://{args.host}:{args.port}/")
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
