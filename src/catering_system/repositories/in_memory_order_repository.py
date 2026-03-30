"""In-memory order repository — B1/B2 baseline."""

from __future__ import annotations

from catering_system.domain.order import Order, OrderVersion


class InMemoryOrderRepository:
    def __init__(self) -> None:
        self._orders: dict[str, Order] = {}
        self._versions: dict[str, OrderVersion] = {}

    def save_order(self, order: Order) -> None:
        self._orders[order.order_id] = order

    def get_order(self, order_id: str) -> Order | None:
        return self._orders.get(order_id)

    def update_order(self, order: Order) -> None:
        if order.order_id not in self._orders:
            raise KeyError(order.order_id)
        self._orders[order.order_id] = order

    def save_order_version(self, version: OrderVersion) -> None:
        self._versions[version.order_version_id] = version

    def get_order_version(self, order_version_id: str) -> OrderVersion | None:
        return self._versions.get(order_version_id)

    def list_order_versions(self, order_id: str) -> list[OrderVersion]:
        rows = [v for v in self._versions.values() if v.order_id == order_id]
        return sorted(rows, key=lambda v: v.version_number)
