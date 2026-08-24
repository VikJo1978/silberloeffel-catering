"""Fail-closed import of explicit production-capacity facts for CAP-5."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from catering_system.domain.production_capacity import (
    CatalogStationRequirement,
    ProductionStation,
    ProductionStationCapacityDay,
)
from catering_system.repositories.sqlite_catalog_repository import SQLiteCatalogRepository
from catering_system.repositories.sqlite_production_capacity_repository import (
    SQLiteProductionCapacityRepository,
)


@dataclass(frozen=True)
class ProductionCapacityImportPlan:
    stations: tuple[ProductionStation, ...]
    requirements: tuple[CatalogStationRequirement, ...]
    capacity_days: tuple[ProductionStationCapacityDay, ...]


@dataclass(frozen=True)
class ProductionCapacityImportResult:
    stations: int
    requirements: int
    capacity_days: int


def _object(value: object, *, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return {str(key): item for key, item in value.items()}


def _array(value: object, *, label: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list")
    return value


def _exact_keys(row: dict[str, object], expected: set[str], *, label: str) -> None:
    keys = set(row)
    if keys != expected:
        missing = sorted(expected - keys)
        extra = sorted(keys - expected)
        details: list[str] = []
        if missing:
            details.append("missing=" + ",".join(missing))
        if extra:
            details.append("unknown=" + ",".join(extra))
        raise ValueError(f"{label} has invalid fields ({'; '.join(details)})")


def _text(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _boolean(value: object, *, label: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{label} must be boolean")
    return value


def _integer(value: object, *, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{label} must be an integer")
    return value


def _date(value: object, *, label: str) -> date:
    text = _text(value, label=label)
    try:
        parsed = date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{label} must be YYYY-MM-DD") from exc
    if parsed.isoformat() != text:
        raise ValueError(f"{label} must be YYYY-MM-DD")
    return parsed


def parse_production_capacity_config(payload: object) -> ProductionCapacityImportPlan:
    """Parse a strict JSON-shaped config without inventing defaults."""

    root = _object(payload, label="config")
    _exact_keys(root, {"stations", "requirements", "capacity_days"}, label="config")

    stations: list[ProductionStation] = []
    station_ids: set[str] = set()
    for index, raw in enumerate(_array(root["stations"], label="stations")):
        row = _object(raw, label=f"stations[{index}]")
        _exact_keys(row, {"station_id", "name", "active"}, label=f"stations[{index}]")
        station = ProductionStation(
            station_id=_text(row["station_id"], label=f"stations[{index}].station_id"),
            name=_text(row["name"], label=f"stations[{index}].name"),
            active=_boolean(row["active"], label=f"stations[{index}].active"),
        )
        if station.station_id in station_ids:
            raise ValueError(f"duplicate station_id: {station.station_id}")
        station_ids.add(station.station_id)
        stations.append(station)

    requirements: list[CatalogStationRequirement] = []
    requirement_keys: set[tuple[str, str]] = set()
    for index, raw in enumerate(_array(root["requirements"], label="requirements")):
        row = _object(raw, label=f"requirements[{index}]")
        _exact_keys(
            row,
            {"catalog_item_id", "station_id", "load_units_per_item"},
            label=f"requirements[{index}]",
        )
        requirement = CatalogStationRequirement(
            catalog_item_id=_text(
                row["catalog_item_id"], label=f"requirements[{index}].catalog_item_id"
            ),
            station_id=_text(
                row["station_id"], label=f"requirements[{index}].station_id"
            ),
            load_units_per_item=_integer(
                row["load_units_per_item"],
                label=f"requirements[{index}].load_units_per_item",
            ),
        )
        key = (requirement.catalog_item_id, requirement.station_id)
        if key in requirement_keys:
            raise ValueError(
                "duplicate requirement: "
                f"{requirement.catalog_item_id}/{requirement.station_id}"
            )
        requirement_keys.add(key)
        requirements.append(requirement)

    capacity_days: list[ProductionStationCapacityDay] = []
    capacity_keys: set[tuple[date, str]] = set()
    for index, raw in enumerate(_array(root["capacity_days"], label="capacity_days")):
        row = _object(raw, label=f"capacity_days[{index}]")
        _exact_keys(
            row,
            {"event_date", "station_id", "capacity_units", "unavailable"},
            label=f"capacity_days[{index}]",
        )
        capacity = ProductionStationCapacityDay(
            event_date=_date(
                row["event_date"], label=f"capacity_days[{index}].event_date"
            ),
            station_id=_text(
                row["station_id"], label=f"capacity_days[{index}].station_id"
            ),
            capacity_units=_integer(
                row["capacity_units"], label=f"capacity_days[{index}].capacity_units"
            ),
            unavailable=_boolean(
                row["unavailable"], label=f"capacity_days[{index}].unavailable"
            ),
        )
        key = (capacity.event_date, capacity.station_id)
        if key in capacity_keys:
            raise ValueError(
                f"duplicate capacity day: {capacity.event_date}/{capacity.station_id}"
            )
        capacity_keys.add(key)
        capacity_days.append(capacity)

    return ProductionCapacityImportPlan(
        stations=tuple(stations),
        requirements=tuple(requirements),
        capacity_days=tuple(capacity_days),
    )


def apply_production_capacity_config(
    db_path: str | Path,
    plan: ProductionCapacityImportPlan,
    *,
    dry_run: bool = False,
) -> ProductionCapacityImportResult:
    """Validate references, then atomically upsert explicit capacity facts."""

    connection = sqlite3.connect(str(db_path))
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        capacity_repo = SQLiteProductionCapacityRepository.from_connection(connection)
        catalog_repo = SQLiteCatalogRepository.from_connection(connection)

        known_station_ids = {
            station.station_id for station in capacity_repo.list_stations()
        } | {station.station_id for station in plan.stations}

        for requirement in plan.requirements:
            if requirement.station_id not in known_station_ids:
                raise ValueError(f"unknown station_id: {requirement.station_id}")
            if catalog_repo.get_dish(requirement.catalog_item_id) is None:
                raise ValueError(
                    f"unknown catalog_item_id: {requirement.catalog_item_id}"
                )
        for capacity in plan.capacity_days:
            if capacity.station_id not in known_station_ids:
                raise ValueError(f"unknown station_id: {capacity.station_id}")

        result = ProductionCapacityImportResult(
            stations=len(plan.stations),
            requirements=len(plan.requirements),
            capacity_days=len(plan.capacity_days),
        )
        if dry_run:
            return result

        with connection:
            for station in plan.stations:
                capacity_repo.upsert_station(station)
            for requirement in plan.requirements:
                capacity_repo.set_catalog_requirement(requirement)
            for capacity in plan.capacity_days:
                capacity_repo.set_capacity_day(capacity)
        return result
    finally:
        connection.close()
