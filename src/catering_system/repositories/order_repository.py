"""Order persistence protocol — Core operational truth."""

from __future__ import annotations

from typing import Protocol

from catering_system.domain.order import Order, OrderVersion


class OrderRepository(Protocol):
    def save_order(self, order: Order) -> None: ...

    def get_order(self, order_id: str) -> Order | None: ...

    def update_order(self, order: Order) -> None: ...

    def save_order_version(self, version: OrderVersion) -> None: ...

    def get_order_version(self, order_version_id: str) -> OrderVersion | None: ...

    def list_order_versions(self, order_id: str) -> list[OrderVersion]: ...
