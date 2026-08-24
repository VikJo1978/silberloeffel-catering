from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pytest

from catering_system.domain.catalog import CatalogDish
from catering_system.repositories.sqlite_catalog_repository import (
    SQLiteCatalogRepository,
)
from catering_system.repositories.sqlite_production_capacity_repository import (
    SQLiteProductionCapacityRepository,
)
from catering_system.services.production_capacity_import import (
    apply_production_capacity_config,
    parse_production_capacity_config,
)


def _dish_id() -> str:
    return str(uuid.uuid4())


def _seed_dish(db_path, dish_id: str) -> None:  # noqa: ANN001
    now = datetime.now(tz=UTC)
    repo = SQLiteCatalogRepository(db_path)
    try:
        assert repo.insert_dish_if_absent(
            CatalogDish(
                dish_id=dish_id,
                name="Test dish",
                description=None,
                composition=None,
                notes=None,
                current_unit_net_cents=1000,
                allergens=(),
                active=True,
                created_at=now,
                updated_at=now,
            )
        )
    finally:
        repo.close()


def _payload(dish_id: str) -> dict[str, object]:
    station = {
        "station_id": "cold",
        "name": "Cold kitchen",
        "active": True,
    }
    requirement = {
        "catalog_item_id": dish_id,
        "station_id": "cold",
        "load_units_per_item": 2,
    }
    capacity_day = {
        "event_date": "2026-08-25",
        "station_id": "cold",
        "capacity_units": 120,
        "unavailable": False,
    }
    return {
        "stations": [station],
        "requirements": [requirement],
        "capacity_days": [capacity_day],
    }


def _first_row(payload: dict[str, object], key: str) -> dict[str, object]:
    rows = payload[key]
    assert isinstance(rows, list)
    assert rows
    row = rows[0]
    assert isinstance(row, dict)
    return row


def test_import_applies_explicit_facts_and_is_idempotent(tmp_path) -> None:
    db_path = tmp_path / "core.db"
    dish_id = _dish_id()
    _seed_dish(db_path, dish_id)
    plan = parse_production_capacity_config(_payload(dish_id))

    first = apply_production_capacity_config(db_path, plan)
    second = apply_production_capacity_config(db_path, plan)

    assert first == second
    assert first.stations == 1
    assert first.requirements == 1
    assert first.capacity_days == 1

    repo = SQLiteProductionCapacityRepository(db_path)
    try:
        stations = repo.list_stations()
        assert [(row.station_id, row.name, row.active) for row in stations] == [
            ("cold", "Cold kitchen", True)
        ]
        requirements = repo.list_catalog_requirements(dish_id)
        assert len(requirements) == 1
        assert requirements[0].load_units_per_item == 2
        capacity = repo.get_capacity_day(date(2026, 8, 25), "cold")
        assert capacity is not None
        assert capacity.capacity_units == 120
        assert capacity.unavailable is False
    finally:
        repo.close()


def test_dry_run_validates_without_writing(tmp_path) -> None:
    db_path = tmp_path / "core.db"
    dish_id = _dish_id()
    _seed_dish(db_path, dish_id)
    plan = parse_production_capacity_config(_payload(dish_id))

    result = apply_production_capacity_config(db_path, plan, dry_run=True)

    assert result.stations == 1
    repo = SQLiteProductionCapacityRepository(db_path)
    try:
        assert repo.list_stations() == []
    finally:
        repo.close()


def test_unknown_catalog_item_fails_before_any_fact_is_written(tmp_path) -> None:
    db_path = tmp_path / "core.db"
    _seed_dish(db_path, _dish_id())
    plan = parse_production_capacity_config(_payload(_dish_id()))

    with pytest.raises(ValueError, match="unknown catalog_item_id"):
        apply_production_capacity_config(db_path, plan)

    repo = SQLiteProductionCapacityRepository(db_path)
    try:
        assert repo.list_stations() == []
    finally:
        repo.close()


def test_unknown_station_reference_fails_closed(tmp_path) -> None:
    db_path = tmp_path / "core.db"
    dish_id = _dish_id()
    _seed_dish(db_path, dish_id)
    payload = _payload(dish_id)
    payload["requirements"] = []
    payload["capacity_days"] = [
        {
            "event_date": "2026-08-25",
            "station_id": "hot",
            "capacity_units": 1,
            "unavailable": False,
        }
    ]
    plan = parse_production_capacity_config(payload)

    with pytest.raises(ValueError, match="unknown station_id: hot"):
        apply_production_capacity_config(db_path, plan)


def test_parser_rejects_duplicates_and_unknown_fields() -> None:
    dish_id = _dish_id()
    payload = _payload(dish_id)
    payload["stations"] = [
        {"station_id": "cold", "name": "Cold", "active": True},
        {"station_id": "cold", "name": "Cold again", "active": True},
    ]
    with pytest.raises(ValueError, match="duplicate station_id"):
        parse_production_capacity_config(payload)

    payload = _payload(dish_id)
    _first_row(payload, "stations")["surprise"] = True
    with pytest.raises(ValueError, match="unknown=surprise"):
        parse_production_capacity_config(payload)


def test_parser_rejects_implicit_or_malformed_business_facts() -> None:
    dish_id = _dish_id()

    payload = _payload(dish_id)
    _first_row(payload, "requirements")["load_units_per_item"] = True
    with pytest.raises(ValueError, match="must be an integer"):
        parse_production_capacity_config(payload)

    payload = _payload(dish_id)
    _first_row(payload, "capacity_days")["event_date"] = "25.08.2026"
    with pytest.raises(ValueError, match="must be YYYY-MM-DD"):
        parse_production_capacity_config(payload)

    payload = _payload(dish_id)
    capacity_day = _first_row(payload, "capacity_days")
    capacity_day["capacity_units"] = 1
    capacity_day["unavailable"] = True
    with pytest.raises(ValueError, match="unavailable station"):
        parse_production_capacity_config(payload)
