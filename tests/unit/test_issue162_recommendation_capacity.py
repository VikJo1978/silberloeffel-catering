from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from catering_system.domain.production_capacity import (
    CatalogStationRequirement,
    ProductionStation,
    ProductionStationCapacityDay,
)
from catering_system.services.recommendation_capacity_service import (
    RecommendationCapacityService,
)

EVENT_DATE = date(2026, 8, 31)
CapacityDay = ProductionStationCapacityDay


def _dish(dish_id: str) -> SimpleNamespace:
    return SimpleNamespace(dish_id=dish_id)


def _order(order_id: str, version_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        order_id=order_id,
        cancelled_at=None,
        effective_order_version_id=version_id,
        candidate_order_version_id=version_id,
    )


def _version(
    order_id: str,
    version_id: str,
    *,
    guest_count_estimate: int | None = 0,
) -> SimpleNamespace:
    return SimpleNamespace(
        order_id=order_id,
        order_version_id=version_id,
        version_number=1,
        event_date=EVENT_DATE,
        guest_count_estimate=guest_count_estimate,
    )


def _position(catalog_item_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        kind="catalog",
        catalog_item_id=catalog_item_id,
        quantity=None,
    )


def _snapshot(*positions: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(positions=positions)


class _Catalog:
    def __init__(self, *dish_ids: str) -> None:
        self._dishes = [_dish(dish_id) for dish_id in dish_ids]

    def list_dishes(self, **_kwargs: object) -> list[SimpleNamespace]:
        return self._dishes


class _Capacity:
    def __init__(
        self,
        requirements: dict[str, list[CatalogStationRequirement]],
        capacity_days: list[CapacityDay],
        stations: list[ProductionStation] | None = None,
    ) -> None:
        self._requirements = requirements
        self._capacity_days = capacity_days
        self._stations = stations or [ProductionStation("cold", "Kalte Küche")]

    def list_stations(self) -> list[ProductionStation]:
        return self._stations

    def list_capacity_days(self, event_date: date) -> list[CapacityDay]:
        assert event_date == EVENT_DATE
        return self._capacity_days

    def list_catalog_requirements(
        self, catalog_item_id: str
    ) -> list[CatalogStationRequirement]:
        return self._requirements.get(catalog_item_id, [])


class _Orders:
    def __init__(
        self,
        orders: list[SimpleNamespace],
        versions: dict[str, SimpleNamespace],
    ) -> None:
        self._orders = orders
        self._versions = versions

    def list_orders(self) -> list[SimpleNamespace]:
        return self._orders

    def get_order_version(self, version_id: str) -> SimpleNamespace | None:
        return self._versions.get(version_id)

    def list_order_versions(self, order_id: str) -> list[SimpleNamespace]:
        return [
            version
            for version in self._versions.values()
            if version.order_id == order_id
        ]


class _Snapshots:
    def __init__(self, snapshots: dict[str, SimpleNamespace]) -> None:
        self._snapshots = snapshots

    def get_by_order_id(self, order_id: str) -> SimpleNamespace | None:
        return self._snapshots.get(order_id)


def _service(
    *,
    dish_ids: tuple[str, ...] = ("dish-a",),
    requirements: dict[str, list[CatalogStationRequirement]],
    capacity_days: list[CapacityDay],
    orders: list[SimpleNamespace] | None = None,
    versions: dict[str, SimpleNamespace] | None = None,
    snapshots: dict[str, SimpleNamespace] | None = None,
    stations: list[ProductionStation] | None = None,
) -> RecommendationCapacityService:
    capacity = _Capacity(requirements, capacity_days, stations)
    return RecommendationCapacityService(  # type: ignore[arg-type]
        _Catalog(*dish_ids),
        capacity,
        _Orders(orders or [], versions or {}),
        _Snapshots(snapshots or {}),
    )


def test_capacity_penalty_uses_committed_guest_count() -> None:
    requirement = CatalogStationRequirement("dish-a", "cold", 1)
    order = _order("order-1", "version-1")
    service = _service(
        requirements={"dish-a": [requirement]},
        capacity_days=[CapacityDay(EVENT_DATE, "cold", 100)],
        orders=[order],
        versions={
            "version-1": _version(
                "order-1", "version-1", guest_count_estimate=40
            )
        },
        snapshots={"order-1": _snapshot(_position("dish-a"))},
    )

    row = service.list_for_date(EVENT_DATE)[0]

    assert row.catalog_item_id == "dish-a"
    assert row.feasible is True
    assert row.overload_penalty == 40
    assert row.reason_code is None


def test_multiple_positions_do_not_multiply_guest_capacity() -> None:
    requirements = {
        "dish-a": [CatalogStationRequirement("dish-a", "cold", 1)],
        "dish-b": [CatalogStationRequirement("dish-b", "cold", 1)],
    }
    order = _order("order-1", "version-1")
    service = _service(
        dish_ids=("dish-a", "dish-b"),
        requirements=requirements,
        capacity_days=[CapacityDay(EVENT_DATE, "cold", 500)],
        orders=[order],
        versions={
            "version-1": _version(
                "order-1", "version-1", guest_count_estimate=100
            )
        },
        snapshots={
            "order-1": _snapshot(_position("dish-a"), _position("dish-b"))
        },
    )

    rows = service.list_for_date(EVENT_DATE)

    assert len(rows) == 2
    assert {row.overload_penalty for row in rows} == {20}


def test_capacity_fails_closed_when_capacity_day_missing() -> None:
    requirement = CatalogStationRequirement("dish-a", "cold", 1)
    service = _service(
        requirements={"dish-a": [requirement]},
        capacity_days=[],
    )

    row = service.list_for_date(EVENT_DATE)[0]

    assert row.feasible is False
    assert row.overload_penalty == 100
    assert row.reason_code == "CAPACITY_UNSET"


def test_capacity_exhausted_when_committed_guests_reach_limit() -> None:
    requirement = CatalogStationRequirement("dish-a", "cold", 1)
    order = _order("order-1", "version-1")
    service = _service(
        requirements={"dish-a": [requirement]},
        capacity_days=[CapacityDay(EVENT_DATE, "cold", 20)],
        orders=[order],
        versions={
            "version-1": _version(
                "order-1", "version-1", guest_count_estimate=20
            )
        },
        snapshots={"order-1": _snapshot(_position("dish-a"))},
    )

    row = service.list_for_date(EVENT_DATE)[0]

    assert row.feasible is False
    assert row.reason_code == "CAPACITY_EXHAUSTED"


def test_capacity_fails_closed_when_demand_is_incomplete() -> None:
    requirement = CatalogStationRequirement("candidate", "cold", 1)
    order = _order("order-1", "version-1")
    service = _service(
        dish_ids=("candidate",),
        requirements={"candidate": [requirement]},
        capacity_days=[CapacityDay(EVENT_DATE, "cold", 100)],
        orders=[order],
        versions={
            "version-1": _version(
                "order-1", "version-1", guest_count_estimate=10
            )
        },
        snapshots={"order-1": _snapshot(_position("legacy-unmapped"))},
    )

    row = service.list_for_date(EVENT_DATE)[0]

    assert row.feasible is False
    assert row.reason_code == "DEMAND_SOURCE_INCOMPLETE"


def test_capacity_fails_closed_for_missing_station_requirement() -> None:
    service = _service(requirements={}, capacity_days=[])

    row = service.list_for_date(EVENT_DATE)[0]

    assert row.feasible is False
    assert row.reason_code == "MISSING_STATION_REQUIREMENT"


def test_cancelled_order_does_not_consume_capacity() -> None:
    requirement = CatalogStationRequirement("dish-a", "cold", 1)
    order = _order("order-1", "version-1")
    order.cancelled_at = object()
    service = _service(
        requirements={"dish-a": [requirement]},
        capacity_days=[CapacityDay(EVENT_DATE, "cold", 100)],
        orders=[order],
        versions={
            "version-1": _version(
                "order-1", "version-1", guest_count_estimate=100
            )
        },
        snapshots={"order-1": _snapshot(_position("dish-a"))},
    )

    row = service.list_for_date(EVENT_DATE)[0]

    assert row.feasible is True
    assert row.overload_penalty == 0


def test_capacity_fails_closed_when_committed_snapshot_is_missing() -> None:
    requirement = CatalogStationRequirement("dish-a", "cold", 1)
    order = _order("order-1", "version-1")
    service = _service(
        requirements={"dish-a": [requirement]},
        capacity_days=[CapacityDay(EVENT_DATE, "cold", 100)],
        orders=[order],
        versions={
            "version-1": _version(
                "order-1", "version-1", guest_count_estimate=10
            )
        },
        snapshots={},
    )

    row = service.list_for_date(EVENT_DATE)[0]

    assert row.feasible is False
    assert row.reason_code == "DEMAND_SOURCE_INCOMPLETE"


def test_capacity_fails_closed_when_guest_count_is_missing() -> None:
    requirement = CatalogStationRequirement("dish-a", "cold", 1)
    order = _order("order-1", "version-1")
    service = _service(
        requirements={"dish-a": [requirement]},
        capacity_days=[CapacityDay(EVENT_DATE, "cold", 100)],
        orders=[order],
        versions={
            "version-1": _version(
                "order-1", "version-1", guest_count_estimate=None
            )
        },
        snapshots={"order-1": _snapshot(_position("dish-a"))},
    )

    row = service.list_for_date(EVENT_DATE)[0]

    assert row.feasible is False
    assert row.reason_code == "DEMAND_SOURCE_INCOMPLETE"


def test_capacity_blocks_inactive_station() -> None:
    requirement = CatalogStationRequirement("dish-a", "cold", 1)
    service = _service(
        requirements={"dish-a": [requirement]},
        capacity_days=[CapacityDay(EVENT_DATE, "cold", 100)],
        stations=[ProductionStation("cold", "Kalte Küche", active=False)],
    )

    row = service.list_for_date(EVENT_DATE)[0]

    assert row.feasible is False
    assert row.reason_code == "STATION_INACTIVE"


def test_capacity_blocks_unavailable_station() -> None:
    requirement = CatalogStationRequirement("dish-a", "cold", 1)
    service = _service(
        requirements={"dish-a": [requirement]},
        capacity_days=[CapacityDay(EVENT_DATE, "cold", 0, unavailable=True)],
    )

    row = service.list_for_date(EVENT_DATE)[0]

    assert row.feasible is False
    assert row.reason_code == "STATION_UNAVAILABLE"


def test_capacity_blocks_zero_station_capacity() -> None:
    requirement = CatalogStationRequirement("dish-a", "cold", 1)
    service = _service(
        requirements={"dish-a": [requirement]},
        capacity_days=[CapacityDay(EVENT_DATE, "cold", 0)],
    )

    row = service.list_for_date(EVENT_DATE)[0]

    assert row.feasible is False
    assert row.reason_code == "NO_CAPACITY"


def test_capacity_falls_back_to_latest_order_version() -> None:
    requirement = CatalogStationRequirement("dish-a", "cold", 1)
    order = SimpleNamespace(
        order_id="order-1",
        cancelled_at=None,
        effective_order_version_id=None,
        candidate_order_version_id=None,
    )
    older = SimpleNamespace(
        order_id="order-1",
        order_version_id="version-1",
        version_number=1,
        event_date=date(2026, 8, 30),
        guest_count_estimate=50,
    )
    latest = SimpleNamespace(
        order_id="order-1",
        order_version_id="version-2",
        version_number=2,
        event_date=EVENT_DATE,
        guest_count_estimate=10,
    )
    service = _service(
        requirements={"dish-a": [requirement]},
        capacity_days=[CapacityDay(EVENT_DATE, "cold", 100)],
        orders=[order],
        versions={"version-1": older, "version-2": latest},
        snapshots={"order-1": _snapshot(_position("dish-a"))},
    )

    row = service.list_for_date(EVENT_DATE)[0]

    assert row.feasible is True
    assert row.overload_penalty == 10
