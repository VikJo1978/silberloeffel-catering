"""Slice 6 OrderDeliverySnapshot contract — reference for PR C.

Test-only frozen operational delivery read model. Production code must match
this contract using only frozen operational delivery facts at conversion.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

DeliveryFulfillmentMode = Literal["DELIVERY", "PICKUP"]

_CREATED_FROM = "accepted_order_conversion"


@dataclass(frozen=True)
class OrderDeliverySnapshotContract:
    order_id: str
    order_version_id: str
    fulfillment_mode: DeliveryFulfillmentMode
    delivery_address: str | None
    delivery_contact: str | None
    time_window_text: str
    location_text: str
    created_from: str = _CREATED_FROM

    def __post_init__(self) -> None:
        if self.created_from != _CREATED_FROM:
            raise ValueError("unsupported delivery snapshot source")


class InMemoryOrderDeliverySnapshotRepository:
    def __init__(self) -> None:
        self._by_version: dict[tuple[str, str], OrderDeliverySnapshotContract] = {}

    def get_by_order_version_id(
        self,
        order_id: str,
        order_version_id: str,
    ) -> OrderDeliverySnapshotContract | None:
        return self._by_version.get((order_id, order_version_id))

    def save(self, snapshot: OrderDeliverySnapshotContract) -> None:
        key = (snapshot.order_id, snapshot.order_version_id)
        existing = self._by_version.get(key)
        if existing is not None and existing != snapshot:
            raise ValueError("order delivery snapshot conflict")
        self._by_version[key] = snapshot


def seed_delivery_snapshot(
    repository: InMemoryOrderDeliverySnapshotRepository,
    *,
    order_id: str,
    order_version_id: str,
    fulfillment_mode: DeliveryFulfillmentMode = "DELIVERY",
    time_window_text: str = "mittags",
    location_text: str = "Hamburg",
    delivery_address: str | None = "Musterstraße 1, Hamburg",
    delivery_contact: str | None = "kunde@example.com",
) -> OrderDeliverySnapshotContract:
    snapshot = OrderDeliverySnapshotContract(
        order_id=order_id,
        order_version_id=order_version_id,
        fulfillment_mode=fulfillment_mode,
        delivery_address=delivery_address if fulfillment_mode == "DELIVERY" else None,
        delivery_contact=delivery_contact,
        time_window_text=time_window_text,
        location_text=location_text,
    )
    repository.save(snapshot)
    return snapshot
