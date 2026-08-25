"""PII-free deterministic production-capacity read model for recommendations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

from catering_system.domain.order import Order, OrderVersion
from catering_system.repositories.catalog_repository import CatalogRepository
from catering_system.repositories.order_repository import OrderRepository
from catering_system.repositories.sqlite_order_commercial_snapshot_repository import (
    SQLiteOrderCommercialSnapshotRepository,
)
from catering_system.repositories.sqlite_production_capacity_repository import (
    SQLiteProductionCapacityRepository,
)

CapacityReasonCode = Literal[
    "MISSING_STATION_REQUIREMENT",
    "STATION_INACTIVE",
    "CAPACITY_UNSET",
    "STATION_UNAVAILABLE",
    "NO_CAPACITY",
    "CAPACITY_EXHAUSTED",
    "DEMAND_SOURCE_INCOMPLETE",
]


@dataclass(frozen=True)
class RecommendationCapacityRow:
    catalog_item_id: str
    feasible: bool
    overload_penalty: int
    reason_code: CapacityReasonCode | None = None
    used_capacity_units: int | None = None
    capacity_units: int | None = None


class RecommendationCapacityService:
    """Project explicit capacity facts plus committed guest demand into item rows.

    Capacity units represent guests for the overall production model. Each accepted
    or confirmed order contributes its ``guest_count_estimate`` once to every
    production station touched by at least one catalog position. Catalog position
    quantities are deliberately not summed: five dishes for 100 guests are 100
    guests of kitchen load, not 500 independent capacity units.

    Sent/open offers remain excluded from committed capacity consumption. They are a
    weak production-overlap signal, not committed kitchen load.
    """

    def __init__(
        self,
        catalog: CatalogRepository,
        capacity: SQLiteProductionCapacityRepository,
        orders: OrderRepository,
        commercial_snapshots: SQLiteOrderCommercialSnapshotRepository,
    ) -> None:
        self._catalog = catalog
        self._capacity = capacity
        self._orders = orders
        self._commercial_snapshots = commercial_snapshots

    def list_for_date(self, event_date: date) -> tuple[RecommendationCapacityRow, ...]:
        stations = {item.station_id: item for item in self._capacity.list_stations()}
        capacity_days = {
            item.station_id: item
            for item in self._capacity.list_capacity_days(event_date)
        }
        used_by_station: dict[str, int] = {}
        global_demand_unknown = False

        for order in self._orders.list_orders():
            if order.cancelled_at is not None:
                continue
            version = self._target_order_version(order)
            if version is None or version.event_date != event_date:
                continue
            snapshot = self._commercial_snapshots.get_by_order_id(order.order_id)
            if snapshot is None:
                global_demand_unknown = True
                continue
            guest_count = version.guest_count_estimate
            if guest_count is None or guest_count < 0:
                global_demand_unknown = True
                continue

            station_ids_for_order: set[str] = set()
            for position in snapshot.positions:
                if position.kind != "catalog" or position.catalog_item_id is None:
                    continue
                requirements = self._capacity.list_catalog_requirements(
                    position.catalog_item_id
                )
                if not requirements:
                    global_demand_unknown = True
                    continue
                for requirement in requirements:
                    if requirement.station_id not in stations:
                        global_demand_unknown = True
                        continue
                    station_ids_for_order.add(requirement.station_id)

            for station_id in station_ids_for_order:
                used_by_station[station_id] = (
                    used_by_station.get(station_id, 0) + guest_count
                )

        rows: list[RecommendationCapacityRow] = []
        for dish in self._catalog.list_dishes(active=True, limit=10_000):
            requirements = self._capacity.list_catalog_requirements(dish.dish_id)
            if not requirements:
                rows.append(self._blocked(dish.dish_id, "MISSING_STATION_REQUIREMENT"))
                continue
            if global_demand_unknown:
                rows.append(self._blocked(dish.dish_id, "DEMAND_SOURCE_INCOMPLETE"))
                continue

            penalty = 0
            blocked_reason: CapacityReasonCode | None = None
            selected_used: int | None = None
            selected_capacity: int | None = None
            for requirement in requirements:
                station = stations.get(requirement.station_id)
                if station is None or not station.active:
                    blocked_reason = "STATION_INACTIVE"
                    break

                used = used_by_station.get(requirement.station_id, 0)
                capacity_day = capacity_days.get(requirement.station_id)
                if capacity_day is None:
                    selected_used = used
                    blocked_reason = "CAPACITY_UNSET"
                    break

                selected_used = used
                selected_capacity = capacity_day.capacity_units
                if capacity_day.unavailable:
                    blocked_reason = "STATION_UNAVAILABLE"
                    break
                if capacity_day.capacity_units == 0:
                    blocked_reason = "NO_CAPACITY"
                    break
                if used >= capacity_day.capacity_units:
                    blocked_reason = "CAPACITY_EXHAUSTED"
                    break

                current_penalty = min(
                    100, (used * 100) // capacity_day.capacity_units
                )
                if current_penalty >= penalty:
                    penalty = current_penalty
                    selected_used = used
                    selected_capacity = capacity_day.capacity_units

            if blocked_reason is not None:
                rows.append(
                    self._blocked(
                        dish.dish_id,
                        blocked_reason,
                        used_capacity_units=selected_used,
                        capacity_units=selected_capacity,
                    )
                )
            else:
                rows.append(
                    RecommendationCapacityRow(
                        catalog_item_id=dish.dish_id,
                        feasible=True,
                        overload_penalty=penalty,
                        used_capacity_units=selected_used,
                        capacity_units=selected_capacity,
                    )
                )

        return tuple(sorted(rows, key=lambda row: row.catalog_item_id))

    def _target_order_version(self, order: Order) -> OrderVersion | None:
        target_id = order.effective_order_version_id or order.candidate_order_version_id
        if target_id is not None:
            version = self._orders.get_order_version(target_id)
            if version is not None and version.order_id == order.order_id:
                return version
        versions = self._orders.list_order_versions(order.order_id)
        return max(versions, key=lambda item: item.version_number, default=None)

    @staticmethod
    def _blocked(
        catalog_item_id: str,
        reason_code: CapacityReasonCode,
        *,
        used_capacity_units: int | None = None,
        capacity_units: int | None = None,
    ) -> RecommendationCapacityRow:
        return RecommendationCapacityRow(
            catalog_item_id=catalog_item_id,
            feasible=False,
            overload_penalty=100,
            reason_code=reason_code,
            used_capacity_units=used_capacity_units,
            capacity_units=capacity_units,
        )
