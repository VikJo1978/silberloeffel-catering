from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from catering_system.domain.production_capacity import (
    CatalogStationRequirement,
    ProductionStation,
    ProductionStationCapacityDay,
)
from catering_system.repositories.sqlite_production_capacity_repository import (
    SQLiteProductionCapacityRepository,
)
from catering_system.services.recommendation_capacity_service import (
    RecommendationCapacityService,
)

EVENT_DATE = date(2026, 8, 31)


def test_capacity_domain_rejects_invalid_facts() -> None:
    with pytest.raises(ValueError):
        ProductionStation(" ", "Cold")
    with pytest.raises(ValueError):
        ProductionStation("cold", " ")
    with pytest.raises(ValueError):
        CatalogStationRequirement(" ", "cold", 1)
    with pytest.raises(ValueError):
        CatalogStationRequirement("dish", " ", 1)
    with pytest.raises(ValueError):
        CatalogStationRequirement("dish", "cold", 0)
    with pytest.raises(ValueError):
        ProductionStationCapacityDay(EVENT_DATE, " ", 1)
    with pytest.raises(ValueError):
        ProductionStationCapacityDay(EVENT_DATE, "cold", -1)
    with pytest.raises(ValueError):
        ProductionStationCapacityDay(EVENT_DATE, "cold", 1, unavailable=True)


def test_sqlite_capacity_repository_roundtrip_and_filters(tmp_path) -> None:
    repo = SQLiteProductionCapacityRepository(tmp_path / "capacity.db")
    try:
        repo.upsert_station(ProductionStation("cold", "Cold", active=True))
        repo.upsert_station(ProductionStation("hot", "Hot", active=False))
        assert [
            station.station_id for station in repo.list_stations(active_only=True)
        ] == ["cold"]

        repo.set_catalog_requirement(CatalogStationRequirement("dish", "cold", 2))
        assert repo.list_catalog_requirements("dish") == [
            CatalogStationRequirement("dish", "cold", 2)
        ]

        capacity = ProductionStationCapacityDay(EVENT_DATE, "cold", 50)
        repo.set_capacity_day(capacity)
        assert repo.get_capacity_day(EVENT_DATE, "cold") == capacity
        assert repo.get_capacity_day(EVENT_DATE, "missing") is None
        assert repo.list_capacity_days(EVENT_DATE) == [capacity]
    finally:
        repo.close()


class _Catalog:
    def __init__(self, *dish_ids: str) -> None:
        self._dish_ids = dish_ids

    def list_dishes(self, **_kwargs: object) -> list[SimpleNamespace]:
        return [SimpleNamespace(dish_id=dish_id) for dish_id in self._dish_ids]


class _Capacity:
    def __init__(
        self,
        requirements: dict[str, list[CatalogStationRequirement]],
        stations: list[ProductionStation],
        days: list[ProductionStationCapacityDay],
    ) -> None:
        self.requirements = requirements
        self.stations = stations
        self.days = days

    def list_stations(self) -> list[ProductionStation]:
        return self.stations

    def list_capacity_days(
        self, _event_date: date
    ) -> list[ProductionStationCapacityDay]:
        return self.days

    def list_catalog_requirements(
        self, catalog_item_id: str
    ) -> list[CatalogStationRequirement]:
        return self.requirements.get(catalog_item_id, [])


class _Orders:
    def __init__(self, orders: list[SimpleNamespace]) -> None:
        self.orders = orders

    def list_orders(self) -> list[SimpleNamespace]:
        return self.orders

    def get_order_version(self, version_id: str) -> SimpleNamespace | None:
        for order in self.orders:
            version = getattr(order, "version", None)
            if version is not None and version.order_version_id == version_id:
                return version
        return None

    def list_order_versions(self, order_id: str) -> list[SimpleNamespace]:
        return [
            order.version
            for order in self.orders
            if order.order_id == order_id and getattr(order, "version", None) is not None
        ]


class _Snapshots:
    def __init__(self, values: dict[str, SimpleNamespace]) -> None:
        self.values = values

    def get_by_order_id(self, order_id: str) -> SimpleNamespace | None:
        return self.values.get(order_id)


def _service(
    *,
    requirements: dict[str, list[CatalogStationRequirement]],
    stations: list[ProductionStation],
    days: list[ProductionStationCapacityDay],
    orders: list[SimpleNamespace] | None = None,
    snapshots: dict[str, SimpleNamespace] | None = None,
) -> RecommendationCapacityService:
    return RecommendationCapacityService(  # type: ignore[arg-type]
        _Catalog("dish"),
        _Capacity(requirements, stations, days),
        _Orders(orders or []),
        _Snapshots(snapshots or {}),
    )


def test_capacity_blocks_inactive_unavailable_and_zero_capacity() -> None:
    requirement = CatalogStationRequirement("dish", "cold", 1)

    inactive = _service(
        requirements={"dish": [requirement]},
        stations=[ProductionStation("cold", "Cold", active=False)],
        days=[ProductionStationCapacityDay(EVENT_DATE, "cold", 10)],
    ).list_for_date(EVENT_DATE)[0]
    assert inactive.reason_code == "STATION_INACTIVE"

    unavailable = _service(
        requirements={"dish": [requirement]},
        stations=[ProductionStation("cold", "Cold")],
        days=[ProductionStationCapacityDay(EVENT_DATE, "cold", 0, unavailable=True)],
    ).list_for_date(EVENT_DATE)[0]
    assert unavailable.reason_code == "STATION_UNAVAILABLE"

    zero = _service(
        requirements={"dish": [requirement]},
        stations=[ProductionStation("cold", "Cold")],
        days=[ProductionStationCapacityDay(EVENT_DATE, "cold", 0)],
    ).list_for_date(EVENT_DATE)[0]
    assert zero.reason_code == "NO_CAPACITY"


def test_capacity_ignores_cancelled_and_non_catalog_positions() -> None:
    requirement = CatalogStationRequirement("dish", "cold", 1)
    version = SimpleNamespace(
        order_id="o1",
        order_version_id="v1",
        version_number=1,
        event_date=EVENT_DATE,
    )
    cancelled = SimpleNamespace(
        order_id="o1",
        cancelled_at=object(),
        effective_order_version_id="v1",
        candidate_order_version_id="v1",
        version=version,
    )
    row = _service(
        requirements={"dish": [requirement]},
        stations=[ProductionStation("cold", "Cold")],
        days=[ProductionStationCapacityDay(EVENT_DATE, "cold", 10)],
        orders=[cancelled],
        snapshots={
            "o1": SimpleNamespace(
                positions=(
                    SimpleNamespace(kind="text", catalog_item_id=None, quantity=None),
                )
            )
        },
    ).list_for_date(EVENT_DATE)[0]
    assert row.feasible is True
    assert row.overload_penalty == 0


def test_capacity_fails_closed_for_missing_snapshot_and_invalid_quantity() -> None:
    requirement = CatalogStationRequirement("dish", "cold", 1)
    version = SimpleNamespace(
        order_id="o1",
        order_version_id="v1",
        version_number=1,
        event_date=EVENT_DATE,
    )
    order = SimpleNamespace(
        order_id="o1",
        cancelled_at=None,
        effective_order_version_id="v1",
        candidate_order_version_id="v1",
        version=version,
    )
    base = dict(
        requirements={"dish": [requirement]},
        stations=[ProductionStation("cold", "Cold")],
        days=[ProductionStationCapacityDay(EVENT_DATE, "cold", 10)],
        orders=[order],
    )

    missing_snapshot = _service(**base).list_for_date(EVENT_DATE)[0]
    assert missing_snapshot.reason_code == "DEMAND_SOURCE_INCOMPLETE"

    invalid_quantity = _service(
        **base,
        snapshots={
            "o1": SimpleNamespace(
                positions=(
                    SimpleNamespace(
                        kind="catalog",
                        catalog_item_id="dish",
                        quantity=Decimal("1.5"),
                    ),
                )
            )
        },
    ).list_for_date(EVENT_DATE)[0]
    assert invalid_quantity.reason_code == "DEMAND_SOURCE_INCOMPLETE"
