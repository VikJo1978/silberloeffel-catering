from __future__ import annotations

from datetime import date
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
        active = repo.list_stations(active_only=True)
        assert [station.station_id for station in active] == ["cold"]

        requirement = CatalogStationRequirement("dish", "cold", 2)
        repo.set_catalog_requirement(requirement)
        assert repo.list_catalog_requirements("dish") == [requirement]

        capacity = ProductionStationCapacityDay(EVENT_DATE, "cold", 50)
        repo.set_capacity_day(capacity)
        assert repo.get_capacity_day(EVENT_DATE, "cold") == capacity
        assert repo.get_capacity_day(EVENT_DATE, "missing") is None
        assert repo.list_capacity_days(EVENT_DATE) == [capacity]
    finally:
        repo.close()


class _Catalog:
    def list_dishes(self, **_kwargs: object) -> list[SimpleNamespace]:
        return [SimpleNamespace(dish_id="dish")]


class _Capacity:
    def __init__(
        self,
        station: ProductionStation,
        capacity: ProductionStationCapacityDay | None,
    ) -> None:
        self.station = station
        self.capacity = capacity

    def list_stations(self) -> list[ProductionStation]:
        return [self.station]

    def list_capacity_days(
        self, _event_date: date
    ) -> list[ProductionStationCapacityDay]:
        if self.capacity is None:
            return []
        return [self.capacity]

    def list_catalog_requirements(
        self, catalog_item_id: str
    ) -> list[CatalogStationRequirement]:
        return [CatalogStationRequirement(catalog_item_id, "cold", 1)]


class _Orders:
    def list_orders(self) -> list[object]:
        return []


def _row(
    station: ProductionStation,
    capacity: ProductionStationCapacityDay | None,
):
    service = RecommendationCapacityService(  # type: ignore[arg-type]
        _Catalog(),
        _Capacity(station, capacity),
        _Orders(),
        object(),
    )
    return service.list_for_date(EVENT_DATE)[0]


def test_capacity_blocks_inactive_station() -> None:
    station = ProductionStation("cold", "Cold", active=False)
    capacity = ProductionStationCapacityDay(EVENT_DATE, "cold", 10)
    assert _row(station, capacity).reason_code == "STATION_INACTIVE"


def test_capacity_blocks_missing_day_capacity() -> None:
    station = ProductionStation("cold", "Cold")
    assert _row(station, None).reason_code == "CAPACITY_UNSET"


def test_capacity_blocks_unavailable_station() -> None:
    station = ProductionStation("cold", "Cold")
    capacity = ProductionStationCapacityDay(
        EVENT_DATE,
        "cold",
        0,
        unavailable=True,
    )
    assert _row(station, capacity).reason_code == "STATION_UNAVAILABLE"


def test_capacity_blocks_zero_capacity() -> None:
    station = ProductionStation("cold", "Cold")
    capacity = ProductionStationCapacityDay(EVENT_DATE, "cold", 0)
    assert _row(station, capacity).reason_code == "NO_CAPACITY"
