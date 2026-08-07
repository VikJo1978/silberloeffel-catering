"""Slice 5 kitchen queue contract — reference for PR C KitchenQueueProjectionService.

This module defines the eligibility + projection boundary only. Production code
must match this contract without reading live Offer or catalog write models.
"""

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


def build_kitchen_queue_projection(
    order_repository: OrderRepository,
    snapshot_repository: OrderCommercialSnapshotRepository,
    *,
    pause_repository: OrderOperationalPauseRepository | None = None,
) -> tuple[KitchenQueueProjectionEntry, ...]:
    """Derived kitchen queue: READY_TO_SEND gate + OrderPrintProjection only."""
    core = OperationalCoreService(
        order_repository,
        pause_repository=pause_repository,
    )
    print_projection = OrderPrintProjectionService(
        order_repository,
        snapshot_repository,
    )
    entries: list[KitchenQueueProjectionEntry] = []
    for order in order_repository.list_orders():
        evaluation = core.evaluate_ready_to_send(order.order_id)
        if not evaluation.ready:
            continue
        effective_id = order.effective_order_version_id
        if effective_id is None:
            continue
        projection = print_projection.resolve(
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
    entries.sort(key=lambda entry: (entry.projection.event.event_date, entry.order_id))
    return tuple(entries)
