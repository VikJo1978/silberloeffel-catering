"""Order commercial snapshot persistence protocol."""

from __future__ import annotations

from typing import Protocol

from catering_system.domain.order_commercial_snapshot import OrderCommercialSnapshot


class OrderCommercialSnapshotRepository(Protocol):
    def create(self, snapshot: OrderCommercialSnapshot) -> None:
        """Insert-only. Duplicate order_id must fail."""

    def get_by_order_id(self, order_id: str) -> OrderCommercialSnapshot | None: ...

    def get_by_id(self, snapshot_id: str) -> OrderCommercialSnapshot | None: ...
