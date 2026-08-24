"""Explicit kitchen station capacity facts for CAP-1 / issue #163."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class ProductionStation:
    station_id: str
    name: str
    active: bool = True

    def __post_init__(self) -> None:
        if not self.station_id.strip():
            raise ValueError("station_id must not be empty")
        if not self.name.strip():
            raise ValueError("station name must not be empty")


@dataclass(frozen=True)
class CatalogStationRequirement:
    catalog_item_id: str
    station_id: str
    load_units_per_item: int

    def __post_init__(self) -> None:
        if not self.catalog_item_id.strip():
            raise ValueError("catalog_item_id must not be empty")
        if not self.station_id.strip():
            raise ValueError("station_id must not be empty")
        if self.load_units_per_item <= 0:
            raise ValueError("load_units_per_item must be positive")


@dataclass(frozen=True)
class ProductionStationCapacityDay:
    event_date: date
    station_id: str
    capacity_units: int
    unavailable: bool = False

    def __post_init__(self) -> None:
        if not self.station_id.strip():
            raise ValueError("station_id must not be empty")
        if self.capacity_units < 0:
            raise ValueError("capacity_units must be non-negative")
        if self.unavailable and self.capacity_units != 0:
            raise ValueError("unavailable station must have zero capacity")
