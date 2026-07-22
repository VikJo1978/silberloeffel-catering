"""In-memory OrderCommercialSnapshot repository."""

from __future__ import annotations

from catering_system.domain.order_commercial_snapshot import OrderCommercialSnapshot


class InMemoryOrderCommercialSnapshotRepository:
    def __init__(self) -> None:
        self._by_id: dict[str, OrderCommercialSnapshot] = {}
        self._by_order_id: dict[str, str] = {}

    def create(self, snapshot: OrderCommercialSnapshot) -> None:
        if snapshot.snapshot_id in self._by_id:
            raise KeyError(snapshot.snapshot_id)
        if snapshot.order_id in self._by_order_id:
            raise ValueError(
                "order commercial snapshot already exists "
                f"(order_id={snapshot.order_id!r})"
            )
        self._by_id[snapshot.snapshot_id] = snapshot
        self._by_order_id[snapshot.order_id] = snapshot.snapshot_id

    def get_by_order_id(self, order_id: str) -> OrderCommercialSnapshot | None:
        snapshot_id = self._by_order_id.get(order_id)
        if snapshot_id is None:
            return None
        return self._by_id.get(snapshot_id)

    def get_by_id(self, snapshot_id: str) -> OrderCommercialSnapshot | None:
        return self._by_id.get(snapshot_id)
