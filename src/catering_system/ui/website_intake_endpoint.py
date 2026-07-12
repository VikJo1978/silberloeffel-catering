"""Website intake receiver — narrow, token-authenticated Core-side endpoint
for the Cloudflare Worker (WORKER_TO_CORE_WEBSITE_INTAKE_PACK_V1).

stdlib-only HTTP server. Exactly one route: POST /intake/website-form.
Creates only an Inquiry, via website_form_adapter — no other Core capability
is reachable through this process; it is not the Office Panel and shares
none of its routes. Not LAN-only by the same DEPLOYMENT.md rule as
office_panel.py, since a Cloudflare Worker must reach it by outbound
HTTP(S) fetch (pack §3) — protected instead by a required bearer token, a
single narrow route, and the adapter's own full field-by-field validation.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer

from catering_system.intake.website_form_adapter import intake_from_website_form
from catering_system.repositories.inquiry_repository import (
    DuplicateExternalReferenceError,
    InquiryRepository,
)
from catering_system.services.inquiry_service import InquiryService

_log = logging.getLogger(__name__)

# Generous above the adapter's own per-field caps (pack §6) — this is a
# second, independent size floor, not a substitute for the Worker's own
# 16 KB cap (defense-in-depth, matching §4's "never trust the previous
# layer alone" principle).
_MAX_BODY_BYTES = 32 * 1024

_ROUTE = "/intake/website-form"


def _parse_event_date(raw: object) -> object:
    """JSON has no date type — convert the ISO string before the adapter
    sees it. Anything that isn't a parseable ISO string is passed through
    unchanged so the adapter's own isinstance(event_date, date) check
    produces its usual, consistent ValueError."""
    if isinstance(raw, str):
        try:
            return date.fromisoformat(raw)
        except ValueError:
            return raw
    return raw


def make_website_intake_handler(
    inquiry_repository: InquiryRepository, token: str
) -> type[BaseHTTPRequestHandler]:
    service = InquiryService(inquiry_repository)
    expected_auth = f"Bearer {token}"

    class WebsiteIntakeHandler(BaseHTTPRequestHandler):
        server_version = "WebsiteIntake/1.0"

        def _json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:  # noqa: N802 (http.server API)
            if self.path != _ROUTE:
                self.send_error(404)
                return
            if self.headers.get("Authorization") != expected_auth:
                _log.warning("website intake: auth rejected")
                self._json(401, {"error": "unauthorized"})
                return
            content_type = self.headers.get("Content-Type", "")
            if not content_type.startswith("application/json"):
                self._json(415, {"error": "unsupported content type"})
                return
            length = int(self.headers.get("Content-Length", "0"))
            if length > _MAX_BODY_BYTES:
                self._json(413, {"error": "payload too large"})
                return
            raw_body = self.rfile.read(length)
            try:
                payload = json.loads(raw_body)
            except ValueError:
                _log.warning("website intake: invalid JSON")
                self._json(400, {"error": "invalid JSON"})
                return
            if not isinstance(payload, dict):
                self._json(400, {"error": "invalid payload"})
                return
            if "event_date" in payload:
                payload = dict(payload)
                payload["event_date"] = _parse_event_date(payload["event_date"])
            # WEBSITE_FORM_INTAKE_IDEMPOTENCY_PACK_V1 §6: a Worker retry with
            # the same submission_id must not create a second Inquiry — reply
            # with the already-existing one instead of calling the adapter
            # again. No submission_id (missing/empty/non-string) means no
            # lookup is possible; current behavior is unchanged in that case.
            submission_id = payload.get("submission_id")
            if isinstance(submission_id, str) and submission_id:
                existing = inquiry_repository.find_by_source_and_external_ref(
                    "website_form", submission_id
                )
                if existing is not None:
                    _log.info(
                        "website intake: duplicate submission_id, "
                        "returning existing inquiry_id=%s",
                        existing.inquiry_id,
                    )
                    self._json(202, {"accepted": True, "inquiry_id": existing.inquiry_id})
                    return
            try:
                inquiry = intake_from_website_form(service, payload)
            except DuplicateExternalReferenceError:
                # Another receiver/process may have inserted this submission
                # after the optimistic lookup above. The repository's unique
                # constraint is authoritative; replay the same accepted result.
                assert isinstance(submission_id, str) and submission_id
                existing = inquiry_repository.find_by_source_and_external_ref(
                    "website_form", submission_id
                )
                if existing is None:
                    _log.error("website intake: duplicate key not resolvable")
                    self._json(500, {"error": "internal error"})
                    return
                _log.info(
                    "website intake: concurrent duplicate submission_id, "
                    "returning existing inquiry_id=%s",
                    existing.inquiry_id,
                )
                self._json(
                    202, {"accepted": True, "inquiry_id": existing.inquiry_id}
                )
                return
            except (ValueError, TypeError) as exc:
                _log.warning("website intake: rejected (%s)", type(exc).__name__)
                self._json(400, {"error": "invalid website_form payload"})
                return
            _log.info("website intake: accepted inquiry_id=%s", inquiry.inquiry_id)
            self._json(202, {"accepted": True, "inquiry_id": inquiry.inquiry_id})

        def _reject(self) -> None:
            self.send_error(405, f"only POST {_ROUTE} is supported")

        do_GET = _reject
        do_PUT = _reject
        do_DELETE = _reject
        do_PATCH = _reject

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            pass  # outcomes are logged explicitly above; no per-request stderr noise

    return WebsiteIntakeHandler


def create_website_intake_server(
    inquiry_repository: InquiryRepository,
    token: str,
    host: str = "0.0.0.0",
    port: int = 8083,
) -> HTTPServer:
    # Single-threaded on purpose: the shared sqlite3 connection must stay on
    # the thread that serves requests (bring-up bug, WORKLOG Entry 048) —
    # same constraint as office_panel.py/kiosk_server.py.
    return HTTPServer((host, port), make_website_intake_handler(inquiry_repository, token))


def main() -> None:
    parser = argparse.ArgumentParser(description="Website form intake receiver (Worker-facing)")
    parser.add_argument("--db", required=True, help="Path to the Core SQLite database")
    parser.add_argument("--port", type=int, default=8083)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument(
        "--token",
        default=os.environ.get("WEBSITE_INTAKE_TOKEN", ""),
        help="Bearer token the Worker must send (or set WEBSITE_INTAKE_TOKEN)",
    )
    args = parser.parse_args()
    if not args.token:
        raise SystemExit(
            "website intake receiver refuses to start without a token "
            "(--token or WEBSITE_INTAKE_TOKEN): it is a write surface"
        )

    from catering_system.repositories.sqlite_inquiry_repository import SQLiteInquiryRepository

    server = create_website_intake_server(
        SQLiteInquiryRepository(args.db), args.token, args.host, args.port
    )
    print(f"Website intake receiver on http://{args.host}:{args.port}{_ROUTE}")
    server.serve_forever()


if __name__ == "__main__":
    main()
