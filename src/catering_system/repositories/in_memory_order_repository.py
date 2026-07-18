"""In-memory order repository — B1/B2 baseline."""

from __future__ import annotations

from dataclasses import replace

from catering_system.domain.order import Order, OrderVersion


class InMemoryOrderRepository:
    def __init__(self) -> None:
        self._orders: dict[str, Order] = {}
        self._versions: dict[str, OrderVersion] = {}

    def save_order_with_initial_version(
        self, order: Order, version: OrderVersion
    ) -> None:
        """Persist both initial records as one in-memory state change."""
        if version.order_id != order.order_id or version.version_number != 1:
            raise ValueError("initial version must be v1 of the supplied order")
        if order.order_id in self._orders:
            raise KeyError(order.order_id)
        if version.order_version_id in self._versions:
            raise KeyError(version.order_version_id)
        next_orders = dict(self._orders)
        next_versions = dict(self._versions)
        next_versions[version.order_version_id] = version
        self._validate_order_references(order, next_versions)
        next_orders[order.order_id] = order
        self._orders = next_orders
        self._versions = next_versions

    def get_order(self, order_id: str) -> Order | None:
        return self._orders.get(order_id)

    def list_orders(self) -> list[Order]:
        return sorted(self._orders.values(), key=lambda o: o.order_id)

    def update_order(self, order: Order) -> None:
        if order.order_id not in self._orders:
            raise KeyError(order.order_id)
        self._validate_order_references(order, self._versions)
        self._orders[order.order_id] = order

    def append_order_version(self, order: Order, version: OrderVersion) -> None:
        """Append a version and update its aggregate root as one state change."""
        if version.order_id != order.order_id or version.version_number < 1:
            raise ValueError("version must belong to the supplied order")
        if order.order_id not in self._orders:
            raise KeyError(order.order_id)
        if version.order_version_id in self._versions:
            raise KeyError(version.order_version_id)
        if any(
            row.order_id == order.order_id
            and row.version_number == version.version_number
            for row in self._versions.values()
        ):
            raise ValueError(
                f"version_number {version.version_number} already exists "
                f"for order {order.order_id!r}"
            )
        next_orders = dict(self._orders)
        next_versions = dict(self._versions)
        next_versions[version.order_version_id] = version
        self._validate_order_references(order, next_versions)
        next_orders[order.order_id] = order
        self._orders = next_orders
        self._versions = next_versions

    def update_order_version(self, version: OrderVersion) -> None:
        existing = self._versions.get(version.order_version_id)
        if existing is None:
            raise KeyError(version.order_version_id)
        if (
            replace(
                existing,
                kitchen_print_confirmed_at=version.kitchen_print_confirmed_at,
            )
            != version
        ):
            raise ValueError("order version snapshot is immutable")
        if (
            existing.kitchen_print_confirmed_at is not None
            and version.kitchen_print_confirmed_at
            != existing.kitchen_print_confirmed_at
        ):
            raise ValueError("kitchen print confirmation is immutable")
        self._versions[version.order_version_id] = version

    @staticmethod
    def _validate_order_references(
        order: Order, versions: dict[str, OrderVersion]
    ) -> None:
        for reference in (
            order.candidate_order_version_id,
            order.effective_order_version_id,
        ):
            if reference is None:
                continue
            version = versions.get(reference)
            if version is None or version.order_id != order.order_id:
                raise ValueError("order version reference is not owned")

    def get_order_version(self, order_version_id: str) -> OrderVersion | None:
        return self._versions.get(order_version_id)

    def list_order_versions(self, order_id: str) -> list[OrderVersion]:
        rows = [v for v in self._versions.values() if v.order_id == order_id]
        return sorted(rows, key=lambda v: v.version_number)
