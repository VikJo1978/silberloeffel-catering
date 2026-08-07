"""Slice 5 kitchen queue contract — delegates to KitchenQueueProjectionService."""

from __future__ import annotations

from catering_system.repositories.order_commercial_snapshot_repository import (
    OrderCommercialSnapshotRepository,
)
from catering_system.repositories.order_operational_pause_repository import (
    OrderOperationalPauseRepository,
)
from catering_system.repositories.order_repository import OrderRepository
from catering_system.services.kitchen_queue_projection_service import (
    KitchenQueueProjectionEntry,
    KitchenQueueProjectionService,
)

__all__ = (
    "KitchenQueueProjectionEntry",
    "build_kitchen_queue_projection",
)


def build_kitchen_queue_projection(
    order_repository: OrderRepository,
    snapshot_repository: OrderCommercialSnapshotRepository,
    *,
    pause_repository: OrderOperationalPauseRepository | None = None,
) -> tuple[KitchenQueueProjectionEntry, ...]:
    """Contract helper used by Slice 5 tests."""
    return KitchenQueueProjectionService(
        order_repository,
        snapshot_repository,
        pause_repository=pause_repository,
    ).list_queue()
