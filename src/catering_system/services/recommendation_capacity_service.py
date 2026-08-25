"""PII-free deterministic production-capacity read model for recommendations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
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
    "CAPACITY_ELEVATED",
    "CAPACITY_HIGH",
    "CAPACITY_NEAR_LIMIT",
    "CAPACITY_EXCEEDED",
    "DEMAND_SOURCE_INCOMPLETE",
]

CAPACITY_WARNING_TEXT: dict[CapacityReasonCode, str] = {
    "MISSING_STATION_REQUIREMENT": "Kapazitätszuordnung fehlt",
    "STATION_INACTIVE": "Produktionsstation ist inaktiv",
    "CAPACITY_UNSET": "Kapazität ist nicht hinterlegt",
    "STATION_UNAVAILABLE": "Produktionsstation ist nicht verfügbar",
    "NO_CAPACITY": "Für die Produktionsstation ist keine Kapazität hinterlegt",
    "CAPACITY_ELEVATED": "Erhöhte Auslastung",
    "CAPACITY_HIGH": "Hohe Auslastung",
    "CAPACITY_NEAR_LIMIT": "Auslastung nahe am empfohlenen Grenzwert",
    "CAPACITY_EXCEEDED": "Empfohlener Kapazitätsgrenzwert überschritten",
    "DEMAND_SOURCE_INCOMPLETE": (
        "Auslastung kann wegen unvollständiger Auftragsdaten nicht vollständig "
        "berechnet werden"
    ),
}


@dataclass(frozen=True)
class RecommendationCapacityRow:
    catalog_item_id: str
    feasible: bool
    overload_penalty: int
    reason_code: CapacityReasonCode | None = None


class RecommendationCapacityService:
    """Project explicit station facts plus accepted/confirmed demand into item rows.

    Sent/open offers are deliberately excluded from capacity consumption. They are a
    weak production-overlap signal, not committed kitchen load.

    Capacity is advisory: this layer reports warnings and ranking penalties but never
    blocks a recommendation. The final decision remains with the employee.
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
            for position in snapshot.positions:
                if position.kind != "catalog" or position.catalog_item_id is None:
                    continue
                quantity = self._whole_quantity(position.quantity)
                requirements = self._capacity.list_catalog_requirements(
                    position.catalog_item_id
                )
                if quantity is None or not requirements:
                    global_demand_unknown = True
                    continue
                for requirement in requirements:
                    if requirement.station_id not in stations:
                        global_demand_unknown = True
                        continue
                    used_by_station[requirement.station_id] = (
                        used_by_station.get(requirement.station_id, 0)
                        + quantity * requirement.load_units_per_item
                    )

        rows: list[RecommendationCapacityRow] = []
        for dish in self._catalog.list_dishes(active=True, limit=10_000):
            requirements = self._capacity.list_catalog_requirements(dish.dish_id)
            if not requirements:
                rows.append(
                    self._advisory(dish.dish_id, "MISSING_STATION_REQUIREMENT")
                )
                continue
            if global_demand_unknown:
                rows.append(self._advisory(dish.dish_id, "DEMAND_SOURCE_INCOMPLETE"))
                continue

            penalty = 0
            warning_reason: CapacityReasonCode | None = None
            for requirement in requirements:
                station = stations.get(requirement.station_id)
                if station is None or not station.active:
                    warning_reason = "STATION_INACTIVE"
                    penalty = 100
                    break
                capacity_day = capacity_days.get(requirement.station_id)
                if capacity_day is None:
                    warning_reason = "CAPACITY_UNSET"
                    penalty = 100
                    break
                if capacity_day.unavailable:
                    warning_reason = "STATION_UNAVAILABLE"
                    penalty = 100
                    break
                if capacity_day.capacity_units == 0:
                    warning_reason = "NO_CAPACITY"
                    penalty = 100
                    break

                used = used_by_station.get(requirement.station_id, 0)
                station_penalty = min(
                    100,
                    (used * 100) // capacity_day.capacity_units,
                )
                if station_penalty > penalty:
                    penalty = station_penalty
                    warning_reason = self._capacity_warning_reason(station_penalty)

            rows.append(
                RecommendationCapacityRow(
                    catalog_item_id=dish.dish_id,
                    feasible=True,
                    overload_penalty=penalty,
                    reason_code=warning_reason,
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
    def _whole_quantity(value: Decimal | None) -> int | None:
        if value is None or value < 0 or value != value.to_integral_value():
            return None
        return int(value)

    @staticmethod
    def _capacity_warning_reason(penalty: int) -> CapacityReasonCode | None:
        if penalty >= 100:
            return "CAPACITY_EXCEEDED"
        if penalty >= 90:
            return "CAPACITY_NEAR_LIMIT"
        if penalty >= 80:
            return "CAPACITY_HIGH"
        if penalty >= 70:
            return "CAPACITY_ELEVATED"
        return None

    @staticmethod
    def _advisory(
        catalog_item_id: str, reason_code: CapacityReasonCode
    ) -> RecommendationCapacityRow:
        return RecommendationCapacityRow(
            catalog_item_id=catalog_item_id,
            feasible=True,
            overload_penalty=100,
            reason_code=reason_code,
        )
