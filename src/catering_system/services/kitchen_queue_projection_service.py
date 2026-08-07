"""Derived kitchen queue from READY_TO_SEND facts + OrderPrintProjection."""

from __future__ import annotations

from dataclasses import dataclass

from catering_system.repositories.order_commercial_snapshot_repository import (
    OrderCommercialSnapshotRepository,
)
from catering_system.repositories.order_operational_pause_repository import (
    OrderOperationalPauseRepository,
)
from catering_system.repositories.order_repository import OrderRepository
from catering_system.services.operational_core_service import OperationalCoreService
from catering_system.services.order_print_projection_service import (
    OrderPrintProjection,
    OrderPrintProjectionService,
)


@dataclass(frozen=True)
class KitchenQueueProjectionEntry:
    order_id: str
    order_version_id: str
    projection: OrderPrintProjection


class KitchenQueueProjectionService:
    def __init__(
        self,
        order_repository: OrderRepository,
        snapshot_repository: OrderCommercialSnapshotRepository,
        *,
        pause_repository: OrderOperationalPauseRepository | None = None,
    ) -> None:
        self._orders = order_repository
        self._snapshots = snapshot_repository
        self._core = OperationalCoreService(
            order_repository,
            pause_repository=pause_repository,
        )
        self._print_projection = OrderPrintProjectionService(
            order_repository,
            snapshot_repository,
        )

    def list_queue(self) -> tuple[KitchenQueueProjectionEntry, ...]:
        entries: list[KitchenQueueProjectionEntry] = []
        for order in self._orders.list_orders():
            evaluation = self._core.evaluate_ready_to_send(order.order_id)
            if not evaluation.ready:
                continue
            effective_id = order.effective_order_version_id
            if effective_id is None:
                continue
            projection = self._print_projection.resolve(
                order.order_id,
                effective_id,
                intent="final",
            )
            entries.append(
                KitchenQueueProjectionEntry(
                    order_id=order.order_id,
                    order_version_id=effective_id,
                    projection=projection,
                )
            )
        entries.sort(
            key=lambda entry: (entry.projection.event.event_date, entry.order_id)
        )
        return tuple(entries)
