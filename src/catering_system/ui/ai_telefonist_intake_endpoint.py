"""Bearer-authenticated STRATO AI telephone intake receiver."""

from __future__ import annotations

import argparse
import hmac
import json
import logging
import os
from datetime import date, time
from http.server import BaseHTTPRequestHandler, HTTPServer

from catering_system.intake.ai_telefonist_adapter import intake_from_ai_telefonist
from catering_system.repositories.inquiry_repository import (
    DuplicateExternalReferenceError,
    InquiryRepository,
)
from catering_system.services.inquiry_service import InquiryService

_log = logging.getLogger(__name__)

_MAX_BODY_BYTES = 32 * 1024
_ROUTE = "/intake/ai-telefonist"


def _parse_event_date(raw: object) -> object:
    if isinstance(raw, str):
        try:
            return date.fromisoformat(raw)
        except ValueError:
            return raw
    return raw


def _parse_event_start(raw: object) -> object:
    if raw is None:
        return None
    if isinstance(raw, str):
        try:
            return time.fromisoformat(raw)
        except ValueError:
            return raw
    return raw


def make_ai_telefonist_intake_handler(
    inquiry_repository: InquiryRepository,
    token: str,
) -> type[BaseHTTPRequestHandler]:
    service = InquiryService(inquiry_repository)
    expected_auth = f"Bearer {token}"

    class AiTelefonistIntakeHandler(BaseHTTPRequestHandler):
        server_version = "AiTelefonistIntake/1.0"

        def end_headers(self) -> None:
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", "default-src 'none'")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            super().end_headers()

        def _json(self, status: int, payload: dict[str, object]) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:  # noqa: N802
            if self.path != _ROUTE:
                self.send_error(404)
                return

            if not hmac.compare_digest(
                self.headers.get("Authorization", ""),
                expected_auth,
            ):
                _log.warning("ai_telefonist intake: auth rejected")
                self._json(401, {"error": "unauthorized"})
                return

            content_type = self.headers.get("Content-Type", "")
            if not content_type.startswith("application/json"):
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

            try:
                payload = json.loads(self.rfile.read(length))
            except ValueError:
                self._json(400, {"error": "invalid JSON"})
                return
            if not isinstance(payload, dict):
                self._json(400, {"error": "invalid payload"})
                return

            payload = dict(payload)
            if "event_date" in payload:
                payload["event_date"] = _parse_event_date(payload["event_date"])
            if "event_start" in payload:
                payload["event_start"] = _parse_event_start(payload["event_start"])

            submission_id = payload.get("submission_id")
            if isinstance(submission_id, str) and submission_id.strip():
                existing = inquiry_repository.find_by_source_and_external_ref(
                    "ai_telefonist",
                    submission_id.strip(),
                )
                if existing is not None:
                    self._json(
                        202,
                        {"accepted": True, "inquiry_id": existing.inquiry_id},
                    )
                    return

            try:
                inquiry = intake_from_ai_telefonist(service, payload)
            except DuplicateExternalReferenceError:
                assert isinstance(submission_id, str) and submission_id.strip()
                existing = inquiry_repository.find_by_source_and_external_ref(
                    "ai_telefonist",
                    submission_id.strip(),
                )
                if existing is None:
                    _log.error("ai_telefonist intake: duplicate key not resolvable")
                    self._json(500, {"error": "internal error"})
                    return
                self._json(
                    202,
                    {"accepted": True, "inquiry_id": existing.inquiry_id},
                )
                return
            except (ValueError, TypeError) as exc:
                _log.warning(
                    "ai_telefonist intake: rejected (%s)",
                    type(exc).__name__,
                )
                self._json(400, {"error": "invalid ai_telefonist payload"})
                return

            _log.info(
                "ai_telefonist intake: accepted inquiry_id=%s",
                inquiry.inquiry_id,
            )
            self._json(202, {"accepted": True, "inquiry_id": inquiry.inquiry_id})

        def _reject(self) -> None:
            self.send_error(405, f"only POST {_ROUTE} is supported")

        do_GET = _reject
        do_PUT = _reject
        do_DELETE = _reject
        do_PATCH = _reject

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            pass

    return AiTelefonistIntakeHandler


def create_ai_telefonist_intake_server(
    inquiry_repository: InquiryRepository,
    token: str,
    host: str = "127.0.0.1",
    port: int = 8085,
) -> HTTPServer:
    return HTTPServer(
        (host, port),
        make_ai_telefonist_intake_handler(inquiry_repository, token),
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="STRATO AI telephone intake receiver"
    )
    parser.add_argument("--db", required=True, help="Path to the Core SQLite database")
    parser.add_argument("--port", type=int, default=8085)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--token",
        default=os.environ.get("AI_TELEFONIST_INTAKE_TOKEN", ""),
        help="Bearer token for STRATO integration",
    )
    args = parser.parse_args()

    if not args.token:
        raise SystemExit(
            "AI telephone intake receiver refuses to start without a token "
            "(--token or AI_TELEFONIST_INTAKE_TOKEN)"
        )

    from catering_system.repositories.sqlite_inquiry_repository import (
        SQLiteInquiryRepository,
    )

    server = create_ai_telefonist_intake_server(
        SQLiteInquiryRepository(args.db),
        args.token,
        args.host,
        args.port,
    )
    print(f"AI telephone intake receiver on http://{args.host}:{args.port}{_ROUTE}")
    server.serve_forever()


if __name__ == "__main__":
    main()
