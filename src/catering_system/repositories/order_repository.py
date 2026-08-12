"""Order persistence protocol — Core operational truth."""

from __future__ import annotations

from typing import Protocol

from catering_system.domain.order import Order, OrderVersion
from catering_system.domain.order_operational_context import (
    OrderVersionOperationalContextSnapshot,
)


class OrderRepository(Protocol):
    def save_order_with_initial_version(
        self,
        order: Order,
        version: OrderVersion,
        operational_context: OrderVersionOperationalContextSnapshot | None = None,
    ) -> None: ...

    def get_order(self, order_id: str) -> Order | None: ...

    def list_orders(self) -> list[Order]: ...

    def update_order(self, order: Order) -> None: ...

    def append_order_version(
        self,
        order: Order,
        version: OrderVersion,
        operational_context: OrderVersionOperationalContextSnapshot | None = None,
    ) -> None: ...

    def update_order_version(self, version: OrderVersion) -> None: ...

    def get_order_version(self, order_version_id: str) -> OrderVersion | None: ...

    def list_order_versions(self, order_id: str) -> list[OrderVersion]: ...

    def get_operational_context(
        self, order_version_id: str
    ) -> OrderVersionOperationalContextSnapshot | None: ...
