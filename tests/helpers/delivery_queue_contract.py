"""Slice 6 delivery queue contract — reference for PR C DeliveryQueueProjectionService.

Eligibility requires KitchenCompletionEvidence plus frozen OrderDeliverySnapshot.
Production modules must use only operational delivery snapshot facts.
"""

from __future__ import annotations

from dataclasses import dataclass

from catering_system.repositories.kitchen_completion_evidence_repository import (
    KitchenCompletionEvidenceRepository,
)
from catering_system.repositories.order_operational_pause_repository import (
    OrderOperationalPauseRepository,
)
from catering_system.repositories.order_repository import OrderRepository
from catering_system.services.operational_core_service import OperationalCoreService
from tests.helpers.delivery_snapshot_contract import (
    InMemoryOrderDeliverySnapshotRepository,
    OrderDeliverySnapshotContract,
)


@dataclass(frozen=True)
class DeliveryQueueProjectionEntry:
    order_id: str
    order_version_id: str
    delivery_snapshot: OrderDeliverySnapshotContract


def build_delivery_queue_projection(
    order_repository: OrderRepository,
    kitchen_completion_repository: KitchenCompletionEvidenceRepository,
    delivery_snapshot_repository: InMemoryOrderDeliverySnapshotRepository,
    *,
    pause_repository: OrderOperationalPauseRepository | None = None,
) -> tuple[DeliveryQueueProjectionEntry, ...]:
    """Derived delivery queue: kitchen completion handoff + frozen delivery snapshot."""
    core = OperationalCoreService(
        order_repository,
        pause_repository=pause_repository,
    )
    entries: list[DeliveryQueueProjectionEntry] = []
    for order in order_repository.list_orders():
        if order.cancelled_at is not None:
            continue
        pause = core.evaluate_ready_to_send(order.order_id)
        if "operational_pause" in pause.reasons:
            continue
        effective_id = order.effective_order_version_id
        if effective_id is None:
            continue
        if (
            kitchen_completion_repository.get_by_order_version_id(
                order.order_id,
                effective_id,
            )
            is None
        ):
            continue
        snapshot = delivery_snapshot_repository.get_by_order_version_id(
            order.order_id,
            effective_id,
        )
        if snapshot is None or snapshot.fulfillment_mode != "DELIVERY":
            continue
        entries.append(
            DeliveryQueueProjectionEntry(
                order_id=order.order_id,
                order_version_id=effective_id,
                delivery_snapshot=snapshot,
            )
        )
    entries.sort(
        key=lambda entry: (
            entry.delivery_snapshot.time_window_text,
            entry.order_id,
        )
    )
    return tuple(entries)
