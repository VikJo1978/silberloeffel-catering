"""Derived delivery queue from kitchen completion + frozen delivery snapshot."""

from __future__ import annotations

from dataclasses import dataclass

from catering_system.domain.order_delivery_snapshot import OrderDeliverySnapshot
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
from catering_system.services.operational_core_service import OperationalCoreService


@dataclass(frozen=True)
class DeliveryQueueProjectionEntry:
    order_id: str
    order_version_id: str
    delivery_snapshot: OrderDeliverySnapshot


class DeliveryQueueProjectionService:
    def __init__(
        self,
        order_repository: OrderRepository,
        kitchen_completion_repository: KitchenCompletionEvidenceRepository,
        delivery_snapshot_repository: OrderDeliverySnapshotRepository,
        *,
        pause_repository: OrderOperationalPauseRepository | None = None,
    ) -> None:
        self._orders = order_repository
        self._kitchen_completion = kitchen_completion_repository
        self._delivery_snapshots = delivery_snapshot_repository
        self._core = OperationalCoreService(
            order_repository,
            pause_repository=pause_repository,
        )

    def list_queue(self) -> tuple[DeliveryQueueProjectionEntry, ...]:
        entries: list[DeliveryQueueProjectionEntry] = []
        for order in self._orders.list_orders():
            if order.cancelled_at is not None:
                continue
            evaluation = self._core.evaluate_ready_to_send(order.order_id)
            if "operational_pause" in evaluation.reasons:
                continue
            effective_id = order.effective_order_version_id
            if effective_id is None:
                continue
            if (
                self._kitchen_completion.get_by_order_version_id(
                    order.order_id,
                    effective_id,
                )
                is None
            ):
                continue
            snapshot = self._delivery_snapshots.get_by_order_version_id(
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
