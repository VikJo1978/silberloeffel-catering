"""In-memory OrderDeliverySnapshot repository for tests."""

from __future__ import annotations

from catering_system.domain.order_delivery_snapshot import OrderDeliverySnapshot


class InMemoryOrderDeliverySnapshotRepository:
    def __init__(self) -> None:
        self._by_version: dict[tuple[str, str], OrderDeliverySnapshot] = {}

    def get_by_order_version_id(
        self,
        order_id: str,
        order_version_id: str,
    ) -> OrderDeliverySnapshot | None:
        return self._by_version.get((order_id, order_version_id))

    def create(self, snapshot: OrderDeliverySnapshot) -> None:
        key = (snapshot.order_id, snapshot.order_version_id)
        if key in self._by_version:
            raise ValueError("order delivery snapshot already exists")
        self._by_version[key] = snapshot
