"""Kitchen execution commands — queue eligibility and completion evidence."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable
from datetime import datetime, timezone
from uuid import uuid4

from catering_system.domain.kitchen_completion_evidence import KitchenCompletionEvidence
from catering_system.repositories.kitchen_completion_evidence_repository import (
    KitchenCompletionEvidenceRepository,
)
from catering_system.repositories.order_operational_pause_repository import (
    OrderOperationalPauseRepository,
)
from catering_system.repositories.order_repository import OrderRepository
from catering_system.services.operational_core_service import OperationalCoreService


class KitchenCompletionBlockedError(ValueError):
    """Completion rejected because operational release facts are unsatisfied."""

    def __init__(self, reasons: tuple[str, ...]) -> None:
        super().__init__("kitchen completion blocked")
        self.reasons = reasons


class KitchenCompletionConflictError(ValueError):
    """Completion evidence already exists with different facts."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class KitchenCompletionRecordResult:
    evidence: KitchenCompletionEvidence
    replay: bool


class KitchenExecutionService:
    def __init__(
        self,
        order_repository: OrderRepository,
        evidence_repository: KitchenCompletionEvidenceRepository,
        *,
        pause_repository: OrderOperationalPauseRepository | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._orders = order_repository
        self._evidence = evidence_repository
        self._core = OperationalCoreService(
            order_repository,
            pause_repository=pause_repository,
        )
        self._clock = clock or _utc_now

    def record_kitchen_completion(
        self,
        order_id: str,
        order_version_id: str,
        *,
        completed_at: datetime,
        recorded_by: str,
        evidence_reference: str,
    ) -> KitchenCompletionRecordResult:
        order = self._orders.get_order(order_id)
        if order is None:
            raise ValueError("order not found")
        if order.cancelled_at is not None:
            raise ValueError("order cancelled")
        version = self._orders.get_order_version(order_version_id)
        if version is None or version.order_id != order_id:
            raise ValueError("order version not owned")

        evaluation = self._core.evaluate_ready_to_send(order_id)
        if not evaluation.ready:
            raise KitchenCompletionBlockedError(evaluation.reasons)

        if order.effective_order_version_id != order_version_id:
            raise ValueError("order version is not effective")

        existing = self._evidence.get_by_order_version_id(order_id, order_version_id)
        candidate = KitchenCompletionEvidence(
            kitchen_completion_evidence_id=(
                existing.kitchen_completion_evidence_id
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
                raise KitchenCompletionConflictError()
            return KitchenCompletionRecordResult(evidence=existing, replay=True)

        self._evidence.append(candidate)
        return KitchenCompletionRecordResult(evidence=candidate, replay=False)
