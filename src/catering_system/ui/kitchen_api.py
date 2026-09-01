"""Kitchen Print Agent HTTP API — transport-only layer (Phase 3B).

Logs carry route, status, command_id and opaque Core IDs only — never PII.
"""

from __future__ import annotations

import base64
import hmac
import json
import logging
import re
from collections.abc import Callable
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Protocol
from uuid import UUID

from catering_system.domain.kitchen_print_job import KitchenPrintPolicy
from catering_system.repositories.in_memory_kitchen_print_document_store import (
    InMemoryKitchenPrintDocumentStore,
)
from catering_system.repositories.kitchen_api_ledger import (
    KitchenCommandLedger,
    RecordedKitchenCommand,
    kitchen_command_fingerprint,
)
from catering_system.repositories.kitchen_print_document_store import (
    KitchenPrintDocumentStore,
)
from catering_system.repositories.sqlite_kitchen_print_job_repository import (
    SQLiteKitchenPrintJobRepository,
)
from catering_system.repositories.sqlite_order_commercial_snapshot_repository import (
    SQLiteOrderCommercialSnapshotRepository,
)
from catering_system.repositories.sqlite_order_confirmation_document_repository import (
    SQLiteOrderConfirmationDocumentRepository,
)
from catering_system.repositories.sqlite_order_repository import SQLiteOrderRepository
from catering_system.services.kitchen_print_application_service import (
    KitchenPrintApplicationService,
)
from catering_system.services.kitchen_print_document_factory import (
    KitchenPrintDocumentFactory,
)
from catering_system.services.kitchen_print_service import KitchenPrintService
from catering_system.services.order_print_projection_service import (
    OrderPrintProjectionService,
)
from catering_system.ui.office_api import ApiError, strict_json_loads

_log = logging.getLogger(__name__)

_MAX_BODY_BYTES = 4096
_CLAIM_ROUTE = "POST /kitchen/v1/print-jobs/claim-next"
_REJECT_ROUTE = "POST /kitchen/v1/print-jobs/{print_job_id}/reject"
_ACK_ROUTE = "POST /kitchen/v1/print-jobs/{print_job_id}/ack"
_UUID4 = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


class _KitchenLedger(Protocol):
    def get(self, command_id: str) -> RecordedKitchenCommand | None: ...

    def record(
        self,
        command_id: str,
        fingerprint: str,
        result_status: int,
        result_body: str,
    ) -> None: ...


def _invalid() -> ApiError:
    return ApiError(422, "invalid_request")


def _v_uuid(value: object) -> str:
    if not isinstance(value, str) or not _UUID4.match(value):
        raise _invalid()
    parsed = UUID(value)
    if parsed.version != 4 or str(parsed) != value:
        raise _invalid()
    return value


def _utc_now() -> datetime:
    return datetime.now(UTC)


class KitchenApi:
    def __init__(
        self,
        db_path: str,
        *,
        ledger: _KitchenLedger | None = None,
        document_store: KitchenPrintDocumentStore | None = None,
        policy: KitchenPrintPolicy | None = None,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._db_path = db_path
        self._ledger = ledger
        self._document_store = (
            document_store
            if document_store is not None
            else InMemoryKitchenPrintDocumentStore()
        )
        self._policy = policy if policy is not None else KitchenPrintPolicy()
        self._clock = clock
        self._orders = SQLiteOrderRepository(db_path)
        self._jobs = SQLiteKitchenPrintJobRepository(db_path)
        self._snapshots = SQLiteOrderCommercialSnapshotRepository(db_path)
        self._confirmation_documents = SQLiteOrderConfirmationDocumentRepository(
            db_path
        )
        self._print_service = KitchenPrintService(
            self._orders,
            self._jobs,
            policy=self._policy,
            clock=self._clock,
        )
        projection_service = OrderPrintProjectionService(
            self._orders,
            self._snapshots,
            self._confirmation_documents,
        )
        self._document_factory = KitchenPrintDocumentFactory(
            projection_service,
            self._document_store,
        )
        self.application = KitchenPrintApplicationService(
            self._print_service,
            self._document_factory,
        )

    @property
    def ledger(self) -> _KitchenLedger:
        if self._ledger is None:
            raise RuntimeError("kitchen ledger is not configured")
        return self._ledger

    def close(self) -> None:
        self._jobs.close()
        self._snapshots.close()
        self._confirmation_documents.close()
        self._orders.close()

    def execute_claim(self, command_id: str) -> tuple[int, str]:
        fingerprint = kitchen_command_fingerprint(
            route_template=_CLAIM_ROUTE,
            command_id=command_id,
        )
        recorded = self.ledger.get(command_id)
        if recorded is not None:
            if not hmac.compare_digest(recorded.fingerprint, fingerprint):
                raise ApiError(409, "command_id_conflict")
            return recorded.result_status, recorded.result_body

        result = self.application.claim_next_with_document()
        if result is None:
            body = json.dumps({"command_id": command_id, "job": None}, sort_keys=True)
            self.ledger.record(command_id, fingerprint, 204, body)
            return 204, body

        job = result.job
        document = result.document
        payload = {
            "command_id": command_id,
            "print_job_id": job.print_job_id,
            "order_id": job.order_id,
            "order_version_id": job.order_version_id,
            "accepted_at": job.accepted_at.isoformat()
            if job.accepted_at is not None
            else None,
            "ack_deadline_at": job.ack_deadline_at.isoformat()
            if job.ack_deadline_at is not None
            else None,
            "document_ref": document.document_ref,
            "document": {
                "content_type": document.content_type,
                "body_base64": base64.b64encode(document.body).decode("ascii"),
            },
        }
        body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        self.ledger.record(command_id, fingerprint, 200, body)
        return 200, body

    def execute_ack(self, print_job_id: str, *, command_id: str) -> tuple[int, str]:
        fingerprint = kitchen_command_fingerprint(
            route_template=_ACK_ROUTE,
            command_id=command_id,
            args={"print_job_id": print_job_id},
        )
        recorded = self.ledger.get(command_id)
        if recorded is not None:
            if not hmac.compare_digest(recorded.fingerprint, fingerprint):
                raise ApiError(409, "command_id_conflict")
            return recorded.result_status, recorded.result_body

        acknowledged = self.application.acknowledge_print_job(print_job_id)
        payload = {
            "command_id": command_id,
            "print_job_id": acknowledged.print_job_id,
            "order_id": acknowledged.order_id,
            "order_version_id": acknowledged.order_version_id,
            "acknowledged_at": acknowledged.acknowledged_at.isoformat()
            if acknowledged.acknowledged_at is not None
            else None,
        }
        body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        self.ledger.record(command_id, fingerprint, 200, body)
        return 200, body

    def execute_reject(
        self, print_job_id: str, *, command_id: str, rejection_code: str
    ) -> tuple[int, str]:
        fingerprint = kitchen_command_fingerprint(
            route_template=_REJECT_ROUTE,
            command_id=command_id,
            args={"print_job_id": print_job_id, "rejection_code": rejection_code},
        )
        recorded = self.ledger.get(command_id)
        if recorded is not None:
            if not hmac.compare_digest(recorded.fingerprint, fingerprint):
                raise ApiError(409, "command_id_conflict")
            return recorded.result_status, recorded.result_body

        rejected = self.application.reject_print_job(print_job_id, rejection_code)
        payload = {
            "command_id": command_id,
            "print_job_id": rejected.print_job_id,
            "rejected_at": rejected.rejected_at.isoformat()
            if rejected.rejected_at is not None
            else None,
            "rejection_code": rejected.rejection_code,
        }
        body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        self.ledger.record(command_id, fingerprint, 200, body)
        return 200, body


def make_kitchen_api_handler(
    api: KitchenApi,
    token: str,
) -> type[BaseHTTPRequestHandler]:
    class KitchenApiHandler(BaseHTTPRequestHandler):
        server_version = "KitchenApi/1.0"

        def log_message(self, format: str, *args: object) -> None:
            _log.info(format, *args)

        def _authorized(self) -> bool:
            header = self.headers.get("Authorization", "")
            if not header.startswith("Bearer "):
                return False
            supplied = header[7:]
            return hmac.compare_digest(supplied, token)

        def _error(self, status: int, error: str) -> None:
            payload = json.dumps({"error": error}, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(payload)

        def _respond_json(self, status: int, body: str) -> None:
            payload = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(payload)

        def _read_json_body(self) -> dict[str, object]:
            content_type = self.headers.get("Content-Type", "")
            if content_type.split(";")[0].strip() != "application/json":
                raise ApiError(415, "unsupported_media_type")
            raw_length = self.headers.get("Content-Length")
            if raw_length is None:
                raise _invalid()
            try:
                length = int(raw_length)
            except ValueError as exc:
                raise _invalid() from exc
            if length <= 0 or length > _MAX_BODY_BYTES:
                raise _invalid()
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise _invalid()
            return strict_json_loads(raw)

        def do_POST(self) -> None:
            if not self._authorized():
                self._error(401, "unauthorized")
                return
            try:
                if self.path == "/kitchen/v1/print-jobs/claim-next":
                    body = self._read_json_body()
                    if set(body) != {"command_id"}:
                        raise _invalid()
                    command_id = _v_uuid(body["command_id"])
                    status, response_body = api.execute_claim(command_id)
                    self._respond_json(status, response_body)
                    return

                reject_prefix = "/kitchen/v1/print-jobs/"
                reject_suffix = "/reject"
                ack_suffix = "/ack"
                if self.path.startswith(reject_prefix) and self.path.endswith(
                    ack_suffix
                ):
                    print_job_id = self.path[len(reject_prefix) : -len(ack_suffix)]
                    _v_uuid(print_job_id)
                    body = self._read_json_body()
                    if set(body) != {"command_id"}:
                        raise _invalid()
                    command_id = _v_uuid(body["command_id"])
                    status, response_body = api.execute_ack(
                        print_job_id,
                        command_id=command_id,
                    )
                    self._respond_json(status, response_body)
                    return

                if self.path.startswith(reject_prefix) and self.path.endswith(
                    reject_suffix
                ):
                    print_job_id = self.path[len(reject_prefix) : -len(reject_suffix)]
                    _v_uuid(print_job_id)
                    body = self._read_json_body()
                    if set(body) != {"command_id", "rejection_code"}:
                        raise _invalid()
                    command_id = _v_uuid(body["command_id"])
                    rejection_code = body["rejection_code"]
                    if not isinstance(rejection_code, str) or not rejection_code:
                        raise _invalid()
                    status, response_body = api.execute_reject(
                        print_job_id,
                        command_id=command_id,
                        rejection_code=rejection_code,
                    )
                    self._respond_json(status, response_body)
                    return

                self._error(404, "not_found")
            except ApiError as exc:
                self._error(exc.status, exc.code)
            except ValueError:
                self._error(422, "invalid_request")

        def do_GET(self) -> None:
            self._error(404, "not_found")

    return KitchenApiHandler


def create_kitchen_api_server(
    db_path: str,
    token: str,
    host: str = "127.0.0.1",
    port: int = 0,
    *,
    ledger: _KitchenLedger | None = None,
    document_store: KitchenPrintDocumentStore | None = None,
    clock: Callable[[], datetime] | None = None,
) -> tuple[HTTPServer, KitchenApi]:
    from catering_system.repositories.core_transaction import open_core_connection

    connection = open_core_connection(db_path)
    effective_ledger = (
        ledger if ledger is not None else KitchenCommandLedger(connection)
    )
    api = KitchenApi(
        db_path,
        ledger=effective_ledger,
        document_store=document_store,
        clock=clock or _utc_now,
    )
    server = HTTPServer((host, port), make_kitchen_api_handler(api, token))
    server.kitchen_connection = connection  # type: ignore[attr-defined]
    return server, api


def main() -> None:
    """Run the loopback Kitchen Print Agent API as a long-lived process."""
    import argparse
    import os

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="Catering Kitchen Print Agent API")
    parser.add_argument("--db", required=True, help="Path to the Core SQLite database")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8086)
    args = parser.parse_args()

    token = os.environ.get("KITCHEN_PRINT_AGENT_TOKEN", "")
    if not token:
        raise SystemExit(
            "KITCHEN_PRINT_AGENT_TOKEN is required; refusing to start unauthenticated"
        )

    server, api = create_kitchen_api_server(
        args.db,
        token,
        args.host,
        args.port,
    )
    _log.info(
        "Catering Kitchen Print API on http://%s:%s/kitchen/v1/",
        args.host,
        args.port,
    )
    try:
        server.serve_forever()
    finally:
        server.server_close()
        api.close()


if __name__ == "__main__":
    main()
