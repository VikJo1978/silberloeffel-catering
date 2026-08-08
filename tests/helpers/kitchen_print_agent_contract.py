"""Slice 3B kitchen print agent contract — reference boundary for ADR tests.

CONTRACT REFERENCE: these functions encode PHASE_3B_KITCHEN_PRINT_AGENT_V1
invariants. When production Slice 3B lands, each entry point should delegate
to the real service/repository and drop the inline reference logic.

Tests import only from this module (and existing Slice 3A types), never from
future production agent modules directly.
"""

from __future__ import annotations

import base64
import hashlib
import json
import threading
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from catering_system.domain.kitchen_print_job import (
    KitchenPrintJob,
    KitchenPrintPolicy,
    derive_kitchen_print_job_state,
)
from catering_system.domain.order import Order
from catering_system.repositories.kitchen_print_job_repository import (
    KitchenPrintJobRepository,
)
from catering_system.repositories.order_commercial_snapshot_repository import (
    OrderCommercialSnapshotRepository,
)
from catering_system.repositories.order_repository import OrderRepository
from catering_system.services.order_print_projection_service import (
    OrderPrintProjection,
    PrintFlagsBlock,
    PrintProjectionNotFoundError,
)

_CLAIM_ROUTE = "POST /kitchen/v1/print-jobs/claim-next"
_AGENT_CLIENT_ID = "kitchen-print-agent"
_CLAIM_LOCK = threading.Lock()


@dataclass(frozen=True)
class KitchenPrintDocument:
    """Application DTO — immutable print artifact at claim time (ADR §2.1)."""

    document_ref: str
    print_job_id: str
    projection_hash: str
    content_type: str
    body: bytes
    created_at: datetime


@dataclass(frozen=True)
class AgentClaimResult:
    job: KitchenPrintJob
    document: KitchenPrintDocument


@dataclass(frozen=True)
class RecordedAgentCommand:
    command_id: str
    fingerprint: str
    result_status: int
    result_body: str


def command_fingerprint(
    *,
    command_id: str,
    route_template: str = _CLAIM_ROUTE,
    args: dict[str, object] | None = None,
) -> str:
    canonical = json.dumps(
        {
            "route_template": route_template,
            "command_id": command_id,
            "args": args or {},
            "client_id": _AGENT_CLIENT_ID,
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class InMemoryDocumentStore:
    def __init__(self) -> None:
        self._by_ref: dict[str, KitchenPrintDocument] = {}

    def save(self, document: KitchenPrintDocument) -> None:
        if document.document_ref in self._by_ref:
            existing = self._by_ref[document.document_ref]
            if existing != document:
                raise ValueError("document_ref conflict")
            return
        self._by_ref[document.document_ref] = document

    def get(self, document_ref: str) -> KitchenPrintDocument | None:
        return self._by_ref.get(document_ref)


class InMemoryAgentCommandLedger:
    def __init__(self) -> None:
        self._rows: dict[str, RecordedAgentCommand] = {}

    def get(self, command_id: str) -> RecordedAgentCommand | None:
        return self._rows.get(command_id)

    def record(
        self,
        command_id: str,
        fingerprint: str,
        result_status: int,
        result_body: str,
    ) -> None:
        self._rows[command_id] = RecordedAgentCommand(
            command_id=command_id,
            fingerprint=fingerprint,
            result_status=result_status,
            result_body=result_body,
        )


def is_eligible_for_claim(
    job: KitchenPrintJob,
    *,
    now: datetime,
    order: Order | None,
) -> bool:
    if order is not None and order.cancelled_at is not None:
        return False
    if job.accepted_at is not None:
        return False
    if job.rejected_at is not None or job.superseded_at is not None:
        return False
    if job.acknowledged_at is not None:
        return False
    if now >= job.accept_deadline_at:
        return False
    return derive_kitchen_print_job_state(job, now=now, order_cancelled=False) in {
        "awaiting_acceptance",
    }


def _all_jobs(job_repository: KitchenPrintJobRepository) -> tuple[KitchenPrintJob, ...]:
    if hasattr(job_repository, "_jobs"):
        return tuple(job_repository._jobs.values())  # type: ignore[attr-defined]
    raise TypeError("contract claim requires in-memory job repository for reference scan")


def claim_next_eligible(
    order_repository: OrderRepository,
    job_repository: KitchenPrintJobRepository,
    *,
    now: datetime,
    policy: KitchenPrintPolicy,
    lock: threading.Lock | None = None,
) -> KitchenPrintJob | None:
    """Reference atomic claim — production replaces with repo.claim_next_eligible()."""

    active_lock = lock or _CLAIM_LOCK
    with active_lock:
        eligible: list[KitchenPrintJob] = []
        for job in sorted(
            _all_jobs(job_repository),
            key=lambda row: (row.accept_deadline_at, row.requested_at, row.print_job_id),
        ):
            order = order_repository.get_order(job.order_id)
            if not is_eligible_for_claim(job, now=now, order=order):
                continue
            eligible.append(job)
        if not eligible:
            return None
        target = eligible[0]
        accepted = replace(
            target,
            accepted_at=now,
            ack_deadline_at=now + policy.acknowledgment_timeout,
        )
        job_repository.update(accepted)
        return accepted


def resolve_kitchen_job_projection(
    order_repository: OrderRepository,
    commercial_snapshot_repository: OrderCommercialSnapshotRepository,
    *,
    order_id: str,
    order_version_id: str,
) -> OrderPrintProjection:
    """Reference kitchen_job intent — production uses intent='kitchen_job'."""

    order = order_repository.get_order(order_id)
    version = order_repository.get_order_version(order_version_id)
    if order is None or version is None or version.order_id != order_id:
        raise PrintProjectionNotFoundError(order_version_id)

    snapshot = commercial_snapshot_repository.get_by_order_id(order_id)
    if snapshot is None:
        raise PrintProjectionNotFoundError(order_id)

    from catering_system.services.order_print_projection_service import (
        _commercial_from_snapshot,
        _event_block,
    )

    return OrderPrintProjection(
        event=_event_block(order, version),
        commercial=_commercial_from_snapshot(snapshot, version.guest_count_estimate),
        flags=PrintFlagsBlock(
            intent="kitchen_job",  # type: ignore[arg-type]
            is_preview=False,
            is_final_allowed=False,
            is_stale=False,
            watermark=None,
        ),
    )


def _canonical_projection_json(projection: OrderPrintProjection) -> str:
    event = projection.event
    commercial = projection.commercial
    flags = projection.flags
    payload = {
        "event": {
            "order_id": event.order_id,
            "order_version_id": event.order_version_id,
            "version_number": event.version_number,
            "event_date": event.event_date.isoformat(),
            "time_window_text": event.time_window_text,
            "location_text": event.location_text,
            "guest_count_estimate": event.guest_count_estimate,
            "planning_mode": event.planning_mode,
        },
        "commercial": {
            "source": commercial.source,
            "variant_label": commercial.variant_label,
            "positions": [
                {
                    "position_id": line.position_id,
                    "name": line.name,
                    "quantity_display": line.quantity_display,
                }
                for line in commercial.positions
            ],
        },
        "flags": {
            "intent": flags.intent,
            "watermark": flags.watermark,
            "is_preview": flags.is_preview,
            "is_stale": flags.is_stale,
        },
    }
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def create_kitchen_print_document(
    projection: OrderPrintProjection,
    job: KitchenPrintJob,
    *,
    now: datetime,
    render_html: Callable[[OrderPrintProjection], str] | None = None,
) -> KitchenPrintDocument:
    projection_hash = hashlib.sha256(
        _canonical_projection_json(projection).encode("utf-8")
    ).hexdigest()
    if render_html is not None:
        body = render_html(projection).encode("utf-8")
    else:
        body = _minimal_kitchen_html(projection).encode("utf-8")
    document_ref = f"sha256:{hashlib.sha256(body).hexdigest()}"
    return KitchenPrintDocument(
        document_ref=document_ref,
        print_job_id=job.print_job_id,
        projection_hash=projection_hash,
        content_type="text/html; charset=utf-8",
        body=body,
        created_at=now,
    )


def _minimal_kitchen_html(projection: OrderPrintProjection) -> str:
    event = projection.event
    lines = [
        "<html><body>",
        f"<p>order_version_id={event.order_version_id}</p>",
        f"<p>version_number={event.version_number}</p>",
        f"<p>location={event.location_text}</p>",
    ]
    for position in projection.commercial.positions:
        lines.append(f"<p>{position.name}</p>")
    lines.append("</body></html>")
    return "".join(lines)


def claim_with_document(
    order_repository: OrderRepository,
    job_repository: KitchenPrintJobRepository,
    commercial_snapshot_repository: OrderCommercialSnapshotRepository,
    document_store: InMemoryDocumentStore,
    *,
    now: datetime,
    policy: KitchenPrintPolicy,
) -> AgentClaimResult | None:
    job = claim_next_eligible(
        order_repository,
        job_repository,
        now=now,
        policy=policy,
    )
    if job is None:
        return None
    projection = resolve_kitchen_job_projection(
        order_repository,
        commercial_snapshot_repository,
        order_id=job.order_id,
        order_version_id=job.order_version_id,
    )
    document = create_kitchen_print_document(projection, job, now=now)
    document_store.save(document)
    return AgentClaimResult(job=job, document=document)


def execute_claim_command(
    *,
    command_id: str,
    order_repository: OrderRepository,
    job_repository: KitchenPrintJobRepository,
    commercial_snapshot_repository: OrderCommercialSnapshotRepository,
    document_store: InMemoryDocumentStore,
    ledger: InMemoryAgentCommandLedger,
    now: datetime,
    policy: KitchenPrintPolicy,
) -> tuple[int, str]:
    fingerprint = command_fingerprint(command_id=command_id)
    recorded = ledger.get(command_id)
    if recorded is not None:
        if recorded.fingerprint != fingerprint:
            raise ValueError("command_id_conflict")
        return recorded.result_status, recorded.result_body

    result = claim_with_document(
        order_repository,
        job_repository,
        commercial_snapshot_repository,
        document_store,
        now=now,
        policy=policy,
    )
    if result is None:
        body = json.dumps({"command_id": command_id, "job": None}, sort_keys=True)
        ledger.record(command_id, fingerprint, 204, body)
        return 204, body

    payload = {
        "command_id": command_id,
        "print_job_id": result.job.print_job_id,
        "order_id": result.job.order_id,
        "order_version_id": result.job.order_version_id,
        "accepted_at": result.job.accepted_at.isoformat()
        if result.job.accepted_at is not None
        else None,
        "ack_deadline_at": result.job.ack_deadline_at.isoformat()
        if result.job.ack_deadline_at is not None
        else None,
        "document_ref": result.document.document_ref,
        "document": {
            "content_type": result.document.content_type,
            "body_base64": base64.b64encode(result.document.body).decode("ascii"),
        },
    }
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    ledger.record(command_id, fingerprint, 200, body)
    return 200, body


def load_document_by_ref(
    document_store: InMemoryDocumentStore,
    document_ref: str,
) -> KitchenPrintDocument:
    document = document_store.get(document_ref)
    if document is None:
        raise LookupError(document_ref)
    return document
