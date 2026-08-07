"""Slice 6 delivery queue contract — delegates to DeliveryQueueProjectionService."""

from __future__ import annotations

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
    DeliveryQueueProjectionEntry,
    DeliveryQueueProjectionService,
)

__all__ = (
    "DeliveryQueueProjectionEntry",
    "build_delivery_queue_projection",
)


def build_delivery_queue_projection(
    order_repository: OrderRepository,
    kitchen_completion_repository: KitchenCompletionEvidenceRepository,
    delivery_snapshot_repository: OrderDeliverySnapshotRepository,
    *,
    pause_repository: OrderOperationalPauseRepository | None = None,
) -> tuple[DeliveryQueueProjectionEntry, ...]:
    return DeliveryQueueProjectionService(
        order_repository,
        kitchen_completion_repository,
        delivery_snapshot_repository,
        pause_repository=pause_repository,
    ).list_queue()
