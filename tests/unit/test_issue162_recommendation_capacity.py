from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from catering_system.domain.production_capacity import (
    CatalogStationRequirement,
    ProductionStation,
    ProductionStationCapacityDay,
)
from catering_system.services.recommendation_capacity_service import (
    CAPACITY_WARNING_TEXT,
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
    guest_count: int | None = 1,
    event_date: date = EVENT_DATE,
    version_number: int = 1,
) -> SimpleNamespace:
    return SimpleNamespace(
        order_id=order_id,
        order_version_id=version_id,
        version_number=version_number,
        event_date=event_date,
        guest_count_estimate=guest_count,
    )


def _position(catalog_item_id: str, quantity: str | None = "1") -> SimpleNamespace:
    return SimpleNamespace(
        kind="catalog",
        catalog_item_id=catalog_item_id,
        quantity=None if quantity is None else Decimal(quantity),
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


def _row_for_used_capacity(used: int):  # noqa: ANN202
    requirement = CatalogStationRequirement("dish-a", "cold", 1)
    order = _order("order-1", "version-1")
    service = _service(
        requirements={"dish-a": [requirement]},
        capacity_days=[CapacityDay(EVENT_DATE, "cold", 100)],
        orders=[order],
        versions={
            "version-1": _version("order-1", "version-1", guest_count=used)
        },
        snapshots={"order-1": _snapshot(_position("dish-a"))},
    )
    return service.list_for_date(EVENT_DATE)[0]


def test_capacity_penalty_uses_committed_guest_load() -> None:
    row = _row_for_used_capacity(40)

    assert row.catalog_item_id == "dish-a"
    assert row.feasible is True
    assert row.overload_penalty == 40
    assert row.reason_code is None


def test_multiple_dishes_on_same_station_count_guest_load_once() -> None:
    order = _order("order-1", "version-1")
    requirements = {
        "dish-a": [CatalogStationRequirement("dish-a", "cold", 1)],
        "dish-b": [CatalogStationRequirement("dish-b", "cold", 9)],
    }
    service = _service(
        dish_ids=("dish-a", "dish-b"),
        requirements=requirements,
        capacity_days=[CapacityDay(EVENT_DATE, "cold", 100)],
        orders=[order],
        versions={
            "version-1": _version("order-1", "version-1", guest_count=40)
        },
        snapshots={
            "order-1": _snapshot(_position("dish-a", "40"), _position("dish-b", "40"))
        },
    )

    rows = service.list_for_date(EVENT_DATE)

    assert [row.overload_penalty for row in rows] == [40, 40]
    assert all(row.feasible is True for row in rows)


def test_capacity_warns_in_four_advisory_tiers() -> None:
    expected = (
        (69, None),
        (70, "CAPACITY_ELEVATED"),
        (79, "CAPACITY_ELEVATED"),
        (80, "CAPACITY_HIGH"),
        (89, "CAPACITY_HIGH"),
        (90, "CAPACITY_NEAR_LIMIT"),
        (99, "CAPACITY_NEAR_LIMIT"),
        (100, "CAPACITY_EXCEEDED"),
        (120, "CAPACITY_EXCEEDED"),
    )

    for used, reason_code in expected:
        row = _row_for_used_capacity(used)
        assert row.feasible is True
        assert row.overload_penalty == min(100, used)
        assert row.reason_code == reason_code


def test_capacity_warning_tiers_have_text_labels() -> None:
    assert CAPACITY_WARNING_TEXT["CAPACITY_ELEVATED"] == "Erhöhte Auslastung"
    assert CAPACITY_WARNING_TEXT["CAPACITY_HIGH"] == "Hohe Auslastung"
    assert (
        CAPACITY_WARNING_TEXT["CAPACITY_NEAR_LIMIT"]
        == "Auslastung nahe am empfohlenen Grenzwert"
    )
    assert (
        CAPACITY_WARNING_TEXT["CAPACITY_EXCEEDED"]
        == "Empfohlener Kapazitätsgrenzwert überschritten"
    )


def test_capacity_missing_day_is_advisory() -> None:
    requirement = CatalogStationRequirement("dish-a", "cold", 1)
    service = _service(
        requirements={"dish-a": [requirement]},
        capacity_days=[],
    )

    row = service.list_for_date(EVENT_DATE)[0]

    assert row.feasible is True
    assert row.overload_penalty == 100
    assert row.reason_code == "CAPACITY_UNSET"


def test_capacity_limit_is_advisory() -> None:
    requirement = CatalogStationRequirement("dish-a", "cold", 2)
    order = _order("order-1", "version-1")
    service = _service(
        requirements={"dish-a": [requirement]},
        capacity_days=[CapacityDay(EVENT_DATE, "cold", 20)],
        orders=[order],
        versions={
            "version-1": _version("order-1", "version-1", guest_count=20)
        },
        snapshots={"order-1": _snapshot(_position("dish-a", "10"))},
    )

    row = service.list_for_date(EVENT_DATE)[0]

    assert row.feasible is True
    assert row.overload_penalty == 100
    assert row.reason_code == "CAPACITY_EXCEEDED"


def test_capacity_incomplete_demand_is_advisory() -> None:
    requirement = CatalogStationRequirement("candidate", "cold", 1)
    order = _order("order-1", "version-1")
    service = _service(
        dish_ids=("candidate",),
        requirements={"candidate": [requirement]},
        capacity_days=[CapacityDay(EVENT_DATE, "cold", 100)],
        orders=[order],
        versions={
            "version-1": _version("order-1", "version-1", guest_count=10)
        },
        snapshots={"order-1": _snapshot(_position("legacy-unmapped", "10"))},
    )

    row = service.list_for_date(EVENT_DATE)[0]

    assert row.feasible is True
    assert row.reason_code == "DEMAND_SOURCE_INCOMPLETE"


def test_capacity_missing_station_requirement_is_advisory() -> None:
    service = _service(requirements={}, capacity_days=[])

    row = service.list_for_date(EVENT_DATE)[0]

    assert row.feasible is True
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
            "version-1": _version("order-1", "version-1", guest_count=100)
        },
        snapshots={"order-1": _snapshot(_position("dish-a", "100"))},
    )

    row = service.list_for_date(EVENT_DATE)[0]

    assert row.feasible is True
    assert row.overload_penalty == 0


def test_capacity_missing_committed_snapshot_is_advisory() -> None:
    requirement = CatalogStationRequirement("dish-a", "cold", 1)
    order = _order("order-1", "version-1")
    service = _service(
        requirements={"dish-a": [requirement]},
        capacity_days=[CapacityDay(EVENT_DATE, "cold", 100)],
        orders=[order],
        versions={
            "version-1": _version("order-1", "version-1", guest_count=10)
        },
        snapshots={},
    )

    row = service.list_for_date(EVENT_DATE)[0]

    assert row.feasible is True
    assert row.reason_code == "DEMAND_SOURCE_INCOMPLETE"


def test_capacity_missing_guest_count_is_advisory() -> None:
    requirement = CatalogStationRequirement("dish-a", "cold", 1)
    order = _order("order-1", "version-1")
    service = _service(
        requirements={"dish-a": [requirement]},
        capacity_days=[CapacityDay(EVENT_DATE, "cold", 100)],
        orders=[order],
        versions={
            "version-1": _version("order-1", "version-1", guest_count=None)
        },
        snapshots={"order-1": _snapshot(_position("dish-a"))},
    )

    row = service.list_for_date(EVENT_DATE)[0]

    assert row.feasible is True
    assert row.reason_code == "DEMAND_SOURCE_INCOMPLETE"


def test_capacity_inactive_station_is_advisory() -> None:
    requirement = CatalogStationRequirement("dish-a", "cold", 1)
    service = _service(
        requirements={"dish-a": [requirement]},
        capacity_days=[CapacityDay(EVENT_DATE, "cold", 100)],
        stations=[ProductionStation("cold", "Kalte Küche", active=False)],
    )

    row = service.list_for_date(EVENT_DATE)[0]

    assert row.feasible is True
    assert row.reason_code == "STATION_INACTIVE"


def test_capacity_unavailable_station_is_advisory() -> None:
    requirement = CatalogStationRequirement("dish-a", "cold", 1)
    service = _service(
        requirements={"dish-a": [requirement]},
        capacity_days=[CapacityDay(EVENT_DATE, "cold", 0, unavailable=True)],
    )

    row = service.list_for_date(EVENT_DATE)[0]

    assert row.feasible is True
    assert row.reason_code == "STATION_UNAVAILABLE"


def test_capacity_zero_station_capacity_is_advisory() -> None:
    requirement = CatalogStationRequirement("dish-a", "cold", 1)
    service = _service(
        requirements={"dish-a": [requirement]},
        capacity_days=[CapacityDay(EVENT_DATE, "cold", 0)],
    )

    row = service.list_for_date(EVENT_DATE)[0]

    assert row.feasible is True
    assert row.reason_code == "NO_CAPACITY"


def test_capacity_falls_back_to_latest_order_version() -> None:
    requirement = CatalogStationRequirement("dish-a", "cold", 1)
    order = SimpleNamespace(
        order_id="order-1",
        cancelled_at=None,
        effective_order_version_id=None,
        candidate_order_version_id=None,
    )
    older = _version(
        "order-1",
        "version-1",
        guest_count=90,
        event_date=date(2026, 8, 30),
        version_number=1,
    )
    latest = _version(
        "order-1",
        "version-2",
        guest_count=10,
        version_number=2,
    )
    service = _service(
        requirements={"dish-a": [requirement]},
        capacity_days=[CapacityDay(EVENT_DATE, "cold", 100)],
        orders=[order],
        versions={"version-1": older, "version-2": latest},
        snapshots={"order-1": _snapshot(_position("dish-a", "10"))},
    )

    row = service.list_for_date(EVENT_DATE)[0]

    assert row.feasible is True
    assert row.overload_penalty == 10
