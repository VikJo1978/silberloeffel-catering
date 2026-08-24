from __future__ import annotations

import sqlite3
from datetime import date

import pytest

from catering_system.domain.production_capacity import (
    CatalogStationRequirement,
    ProductionStation,
    ProductionStationCapacityDay,
)
from catering_system.repositories.sqlite_production_capacity_repository import (
    SQLiteProductionCapacityRepository,
)


def test_capacity_source_round_trips_explicit_facts(tmp_path) -> None:
    db_path = tmp_path / "core.db"
    repo = SQLiteProductionCapacityRepository(db_path)
    try:
        repo.upsert_station(ProductionStation("cold-kitchen", "Kalte Küche"))
        repo.set_catalog_requirement(
            CatalogStationRequirement(
                catalog_item_id="dish-1",
                station_id="cold-kitchen",
                load_units_per_item=3,
            )
        )
        repo.set_capacity_day(
            ProductionStationCapacityDay(
                event_date=date(2026, 8, 31),
                station_id="cold-kitchen",
                capacity_units=240,
            )
        )

        assert repo.list_stations(active_only=True) == [
            ProductionStation("cold-kitchen", "Kalte Küche")
        ]
        assert repo.list_catalog_requirements("dish-1") == [
            CatalogStationRequirement("dish-1", "cold-kitchen", 3)
        ]
        assert repo.get_capacity_day(date(2026, 8, 31), "cold-kitchen") == (
            ProductionStationCapacityDay(
                date(2026, 8, 31), "cold-kitchen", 240, unavailable=False
            )
        )
    finally:
        repo.close()


def test_capacity_source_preserves_explicit_unavailable_day(tmp_path) -> None:
    repo = SQLiteProductionCapacityRepository(tmp_path / "core.db")
    try:
        repo.upsert_station(ProductionStation("hot-kitchen", "Warme Küche"))
        repo.set_capacity_day(
            ProductionStationCapacityDay(
                date(2026, 9, 1), "hot-kitchen", 0, unavailable=True
            )
        )
        assert repo.get_capacity_day(date(2026, 9, 1), "hot-kitchen") == (
            ProductionStationCapacityDay(
                date(2026, 9, 1), "hot-kitchen", 0, unavailable=True
            )
        )
    finally:
        repo.close()


def test_capacity_domain_rejects_fake_or_invalid_precision() -> None:
    with pytest.raises(ValueError, match="positive"):
        CatalogStationRequirement("dish-1", "cold-kitchen", 0)
    with pytest.raises(ValueError, match="non-negative"):
        ProductionStationCapacityDay(date(2026, 8, 31), "cold-kitchen", -1)
    with pytest.raises(ValueError, match="zero capacity"):
        ProductionStationCapacityDay(
            date(2026, 8, 31), "cold-kitchen", 10, unavailable=True
        )


def test_capacity_migration_is_registered_separately(tmp_path) -> None:
    db_path = tmp_path / "core.db"
    repo = SQLiteProductionCapacityRepository(db_path)
    repo.close()

    connection = sqlite3.connect(db_path)
    try:
        row = connection.execute(
            """
            SELECT version, name
            FROM schema_migrations
            WHERE component = 'production_capacity'
            """
        ).fetchone()
        assert row == (1, "production_capacity_v1")
    finally:
        connection.close()
