"""Isolated staging website for developing the public inquiry form.

This process never imports production repositories or forwards to Core. Test
submissions are stored in their own SQLite database on the staging host.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import threading
import time
import uuid
from collections import defaultdict, deque
from datetime import date, datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

_ASSET_DIR = Path(__file__).with_name("staging_site_assets")
_MAX_BODY_BYTES = 16 * 1024
_RATE_LIMIT_COUNT = 8
_RATE_LIMIT_WINDOW_SECONDS = 60.0

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
                "INSERT INTO staging_inquiries VALUES "
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
    if guest_count is not None and (guest_count < 1 or guest_count > 5000):
        raise ValueError("guest_count_estimate must be between 1 and 5000")

    return {
        "submission_id": str(uuid.uuid4()),
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


def make_staging_handler(
    repository: StagingInquiryRepository,
    rate_limiter: SubmissionRateLimiter | None = None,
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
                self._json(200, {"status": "ok", "environment": "staging"})
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
            repository.save(inquiry)
            self._json(
                201,
                {
                    "accepted": True,
                    "environment": "staging",
                    "submission_id": inquiry["submission_id"],
                },
            )

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            pass

    return StagingHandler


class StagingHTTPServer(HTTPServer):
    def __init__(self, address: tuple[str, int], db_path: str | Path) -> None:
        self.repository = StagingInquiryRepository(db_path)
        super().__init__(address, make_staging_handler(self.repository))

    def server_close(self) -> None:
        super().server_close()
        self.repository.close()


def create_staging_server(
    db_path: str | Path, host: str = "127.0.0.1", port: int = 8080
) -> StagingHTTPServer:
    return StagingHTTPServer((host, port), db_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Catering inquiry-form staging site")
    parser.add_argument("--db", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    server = create_staging_server(args.db, args.host, args.port)
    print(f"Catering staging site on http://{args.host}:{args.port}/")
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
