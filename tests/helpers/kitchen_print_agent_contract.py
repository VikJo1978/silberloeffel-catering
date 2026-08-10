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
from dataclasses import dataclass
from datetime import datetime

from catering_system.domain.kitchen_print_job import (
    KitchenPrintJob,
    KitchenPrintPolicy,
    derive_kitchen_print_job_state,
)
from catering_system.domain.order import Order
from catering_system.repositories.in_memory_kitchen_print_document_store import (
    InMemoryKitchenPrintDocumentStore,
)
from catering_system.repositories.kitchen_print_job_repository import (
    KitchenPrintJobRepository,
)
from catering_system.repositories.order_commercial_snapshot_repository import (
    OrderCommercialSnapshotRepository,
)
from catering_system.repositories.order_repository import OrderRepository
from catering_system.services.kitchen_print_document import (
    KitchenPrintDocument,
    build_kitchen_print_document,
)
from catering_system.services.kitchen_print_document_factory import (
    KitchenPrintDocumentFactory,
)
from catering_system.services.kitchen_print_service import KitchenPrintService
from catering_system.services.order_print_projection_service import (
    OrderPrintProjection,
    OrderPrintProjectionService,
)

_CLAIM_ROUTE = "POST /kitchen/v1/print-jobs/claim-next"
_AGENT_CLIENT_ID = "kitchen-print-agent"

InMemoryDocumentStore = InMemoryKitchenPrintDocumentStore


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


def claim_next_eligible(
    order_repository: OrderRepository,
    job_repository: KitchenPrintJobRepository,
    *,
    now: datetime,
    policy: KitchenPrintPolicy,
    lock: threading.Lock | None = None,
) -> KitchenPrintJob | None:
    """Delegate atomic claim to production KitchenPrintService."""

    del lock  # repository implementations own concurrency primitives
    service = KitchenPrintService(
        order_repository,
        job_repository,
        policy=policy,
        clock=lambda: now,
    )
    return service.claim_next_eligible()


def resolve_kitchen_job_projection(
    order_repository: OrderRepository,
    commercial_snapshot_repository: OrderCommercialSnapshotRepository,
    *,
    order_id: str,
    order_version_id: str,
) -> OrderPrintProjection:
    """Delegate kitchen_job intent to production OrderPrintProjectionService."""

    return OrderPrintProjectionService(
        order_repository,
        commercial_snapshot_repository,
    ).resolve(order_id, order_version_id, intent="kitchen_job")


def create_kitchen_print_document(
    projection: OrderPrintProjection,
    job: KitchenPrintJob,
    *,
    now: datetime,
) -> KitchenPrintDocument:
    return build_kitchen_print_document(
        projection,
        job,
        now=now,
    )


def claim_with_document(
    order_repository: OrderRepository,
    job_repository: KitchenPrintJobRepository,
    commercial_snapshot_repository: OrderCommercialSnapshotRepository,
    document_store: InMemoryKitchenPrintDocumentStore,
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
    factory = KitchenPrintDocumentFactory(
        OrderPrintProjectionService(
            order_repository,
            commercial_snapshot_repository,
        ),
        document_store,
    )
    document = factory.create_for_print_job(job)
    return AgentClaimResult(job=job, document=document)


def execute_claim_command(
    *,
    command_id: str,
    order_repository: OrderRepository,
    job_repository: KitchenPrintJobRepository,
    commercial_snapshot_repository: OrderCommercialSnapshotRepository,
    document_store: InMemoryKitchenPrintDocumentStore,
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
    document_store: InMemoryKitchenPrintDocumentStore,
    document_ref: str,
) -> KitchenPrintDocument:
    document = document_store.get(document_ref)
    if document is None:
        raise LookupError(document_ref)
    return document
