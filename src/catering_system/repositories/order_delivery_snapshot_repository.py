"""OrderDeliverySnapshot persistence protocol."""

from __future__ import annotations

from typing import Protocol

from catering_system.domain.order_delivery_snapshot import OrderDeliverySnapshot


class OrderDeliverySnapshotRepository(Protocol):
    def get_by_order_version_id(
        self,
        order_id: str,
        order_version_id: str,
    ) -> OrderDeliverySnapshot | None: ...

    def create(self, snapshot: OrderDeliverySnapshot) -> None: ...
