"""Slice 6 OrderDeliverySnapshot test seeding helpers."""

from __future__ import annotations

import uuid

from catering_system.domain.inquiry import FulfillmentMode
from catering_system.domain.order_delivery_snapshot import OrderDeliverySnapshot
from catering_system.repositories.in_memory_order_delivery_snapshot_repository import (
    InMemoryOrderDeliverySnapshotRepository,
)


def seed_delivery_snapshot(
    repository: InMemoryOrderDeliverySnapshotRepository,
    *,
    order_id: str,
    order_version_id: str,
    fulfillment_mode: FulfillmentMode = "DELIVERY",
    time_window_text: str = "mittags",
    location_text: str = "Hamburg",
    delivery_address: str | None = "Musterstraße 1, Hamburg",
    delivery_contact: str | None = "kunde@example.com",
) -> OrderDeliverySnapshot:
    snapshot = OrderDeliverySnapshot(
        snapshot_id=str(uuid.uuid4()),
        order_id=order_id,
        order_version_id=order_version_id,
        fulfillment_mode=fulfillment_mode,
        delivery_address=delivery_address if fulfillment_mode == "DELIVERY" else None,
        delivery_contact=delivery_contact,
        time_window_text=time_window_text,
        location_text=location_text,
    )
    repository.create(snapshot)
    return snapshot
