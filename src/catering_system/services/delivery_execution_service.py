"""Delivery execution commands — dispatch and completion evidence."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from catering_system.domain.delivery_completion_evidence import DeliveryCompletionEvidence
from catering_system.domain.dispatch_evidence import DispatchEvidence
from catering_system.repositories.delivery_completion_evidence_repository import (
    DeliveryCompletionEvidenceRepository,
)
from catering_system.repositories.dispatch_evidence_repository import (
    DispatchEvidenceRepository,
)
from catering_system.repositories.kitchen_completion_evidence_repository import (
    KitchenCompletionEvidenceRepository,
)
from catering_system.repositories.order_delivery_snapshot_repository import (
    OrderDeliverySnapshotRepository,
)
from catering_system.repositories.order_operational_pause_repository import (
    OrderOperationalPauseRepository,
)
from catering_system.repositories.order_repository import OrderRepository
from catering_system.services.delivery_queue_projection_service import (
    DeliveryQueueProjectionService,
)


class DeliveryExecutionBlockedError(ValueError):
    """Dispatch or completion rejected because delivery eligibility is unsatisfied."""


class DeliveryEvidenceConflictError(ValueError):
    """Evidence already exists with different facts."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class DeliveryEvidenceRecordResult:
    evidence: DispatchEvidence | DeliveryCompletionEvidence
    replay: bool


class DeliveryExecutionService:
    def __init__(
        self,
        order_repository: OrderRepository,
        kitchen_completion_repository: KitchenCompletionEvidenceRepository,
        delivery_snapshot_repository: OrderDeliverySnapshotRepository,
        dispatch_repository: DispatchEvidenceRepository,
        delivery_completion_repository: DeliveryCompletionEvidenceRepository,
        *,
        pause_repository: OrderOperationalPauseRepository | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._orders = order_repository
        self._dispatch = dispatch_repository
        self._delivery_completion = delivery_completion_repository
        self._queue = DeliveryQueueProjectionService(
            order_repository,
            kitchen_completion_repository,
            delivery_snapshot_repository,
            pause_repository=pause_repository,
        )
        self._clock = clock or _utc_now

    def _assert_delivery_eligible(self, order_id: str, order_version_id: str) -> None:
        eligible = {
            (entry.order_id, entry.order_version_id) for entry in self._queue.list_queue()
        }
        if (order_id, order_version_id) not in eligible:
            raise DeliveryExecutionBlockedError()

    def record_dispatch(
        self,
        order_id: str,
        order_version_id: str,
        *,
        dispatched_at: datetime,
        recorded_by: str,
        evidence_reference: str,
    ) -> DeliveryEvidenceRecordResult:
        order = self._orders.get_order(order_id)
        if order is None:
            raise ValueError("order not found")
        if order.cancelled_at is not None:
            raise ValueError("order cancelled")
        version = self._orders.get_order_version(order_version_id)
        if version is None or version.order_id != order_id:
            raise ValueError("order version not owned")
        if order.effective_order_version_id != order_version_id:
            raise ValueError("order version is not effective")

        self._assert_delivery_eligible(order_id, order_version_id)

        existing = self._dispatch.get_by_order_version_id(order_id, order_version_id)
        candidate = DispatchEvidence(
            dispatch_evidence_id=(
                existing.dispatch_evidence_id if existing is not None else str(uuid4())
            ),
            order_id=order_id,
            order_version_id=order_version_id,
            dispatched_at=dispatched_at,
            recorded_at=existing.recorded_at if existing is not None else self._clock(),
            recorded_by=recorded_by,
            evidence_reference=evidence_reference,
        )
        if existing is not None:
            if existing != candidate:
                raise DeliveryEvidenceConflictError()
            return DeliveryEvidenceRecordResult(evidence=existing, replay=True)

        self._dispatch.append(candidate)
        return DeliveryEvidenceRecordResult(evidence=candidate, replay=False)

    def record_delivery_completion(
        self,
        order_id: str,
        order_version_id: str,
        *,
        completed_at: datetime,
        recorded_by: str,
        evidence_reference: str,
    ) -> DeliveryEvidenceRecordResult:
        order = self._orders.get_order(order_id)
        if order is None:
            raise ValueError("order not found")
        if order.cancelled_at is not None:
            raise ValueError("order cancelled")
        version = self._orders.get_order_version(order_version_id)
        if version is None or version.order_id != order_id:
            raise ValueError("order version not owned")
        if order.effective_order_version_id != order_version_id:
            raise ValueError("order version is not effective")

        if (
            self._dispatch.get_by_order_version_id(order_id, order_version_id)
            is None
        ):
            raise DeliveryExecutionBlockedError()

        existing = self._delivery_completion.get_by_order_version_id(
            order_id,
            order_version_id,
        )
        candidate = DeliveryCompletionEvidence(
            delivery_completion_evidence_id=(
                existing.delivery_completion_evidence_id
                if existing is not None
                else str(uuid4())
            ),
            order_id=order_id,
            order_version_id=order_version_id,
            completed_at=completed_at,
            recorded_at=existing.recorded_at if existing is not None else self._clock(),
            recorded_by=recorded_by,
            evidence_reference=evidence_reference,
        )
        if existing is not None:
            if existing != candidate:
                raise DeliveryEvidenceConflictError()
            return DeliveryEvidenceRecordResult(evidence=existing, replay=True)

        self._delivery_completion.append(candidate)
        return DeliveryEvidenceRecordResult(evidence=candidate, replay=False)
