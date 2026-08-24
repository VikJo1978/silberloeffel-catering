"""SQLite persistence for explicit kitchen station capacity facts."""

from __future__ import annotations

import sqlite3
from contextlib import nullcontext
from datetime import date
from pathlib import Path

from catering_system.domain.production_capacity import (
    CatalogStationRequirement,
    ProductionStation,
    ProductionStationCapacityDay,
)
from catering_system.repositories.sqlite_migrations import apply_migrations


def _migration_1_create_capacity_tables(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS production_stations (
            station_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            active INTEGER NOT NULL CHECK (active IN (0, 1))
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS catalog_station_requirements (
            catalog_item_id TEXT NOT NULL,
            station_id TEXT NOT NULL,
            load_units_per_item INTEGER NOT NULL CHECK (load_units_per_item > 0),
            PRIMARY KEY (catalog_item_id, station_id),
            FOREIGN KEY (station_id) REFERENCES production_stations (station_id)
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_catalog_station_requirements_station
        ON catalog_station_requirements (station_id, catalog_item_id)
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS production_station_capacity_days (
            event_date TEXT NOT NULL,
            station_id TEXT NOT NULL,
            capacity_units INTEGER NOT NULL CHECK (capacity_units >= 0),
            unavailable INTEGER NOT NULL CHECK (unavailable IN (0, 1)),
            PRIMARY KEY (event_date, station_id),
            FOREIGN KEY (station_id) REFERENCES production_stations (station_id),
            CHECK (unavailable = 0 OR capacity_units = 0)
        )
        """
    )


_MIGRATIONS = ((1, "production_capacity_v1", _migration_1_create_capacity_tables),)


class SQLiteProductionCapacityRepository:
    def __init__(self, db_path: str | Path) -> None:
        self._conn = sqlite3.connect(str(db_path))
        self._manage_transactions = True
        try:
            apply_migrations(self._conn, "production_capacity", _MIGRATIONS)
        except Exception:
            self._conn.close()
            raise

    @classmethod
    def from_connection(
        cls, connection: sqlite3.Connection
    ) -> "SQLiteProductionCapacityRepository":
        repo = cls.__new__(cls)
        repo._conn = connection
        repo._manage_transactions = False
        apply_migrations(connection, "production_capacity", _MIGRATIONS)
        return repo

    def _write_scope(self):  # noqa: ANN202
        return self._conn if self._manage_transactions else nullcontext()

    def close(self) -> None:
        self._conn.close()

    def upsert_station(self, station: ProductionStation) -> None:
        with self._write_scope():
            self._conn.execute(
                """
                INSERT INTO production_stations (station_id, name, active)
                VALUES (?, ?, ?)
                ON CONFLICT(station_id) DO UPDATE SET
                    name = excluded.name,
                    active = excluded.active
                """,
                (station.station_id, station.name, int(station.active)),
            )
            if self._manage_transactions:
                self._conn.commit()

    def list_stations(self, *, active_only: bool = False) -> list[ProductionStation]:
        where = "WHERE active = 1" if active_only else ""
        rows = self._conn.execute(
            f"""
            SELECT station_id, name, active
            FROM production_stations
            {where}
            ORDER BY station_id ASC
            """
        ).fetchall()
        return [
            ProductionStation(
                station_id=str(row[0]), name=str(row[1]), active=bool(row[2])
            )
            for row in rows
        ]

    def set_catalog_requirement(self, requirement: CatalogStationRequirement) -> None:
        with self._write_scope():
            self._conn.execute(
                """
                INSERT INTO catalog_station_requirements (
                    catalog_item_id, station_id, load_units_per_item
                ) VALUES (?, ?, ?)
                ON CONFLICT(catalog_item_id, station_id) DO UPDATE SET
                    load_units_per_item = excluded.load_units_per_item
                """,
                (
                    requirement.catalog_item_id,
                    requirement.station_id,
                    requirement.load_units_per_item,
                ),
            )
            if self._manage_transactions:
                self._conn.commit()

    def list_catalog_requirements(
        self, catalog_item_id: str
    ) -> list[CatalogStationRequirement]:
        rows = self._conn.execute(
            """
            SELECT catalog_item_id, station_id, load_units_per_item
            FROM catalog_station_requirements
            WHERE catalog_item_id = ?
            ORDER BY station_id ASC
            """,
            (catalog_item_id,),
        ).fetchall()
        return [
            CatalogStationRequirement(
                catalog_item_id=str(row[0]),
                station_id=str(row[1]),
                load_units_per_item=int(row[2]),
            )
            for row in rows
        ]

    def set_capacity_day(self, capacity: ProductionStationCapacityDay) -> None:
        with self._write_scope():
            self._conn.execute(
                """
                INSERT INTO production_station_capacity_days (
                    event_date, station_id, capacity_units, unavailable
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(event_date, station_id) DO UPDATE SET
                    capacity_units = excluded.capacity_units,
                    unavailable = excluded.unavailable
                """,
                (
                    capacity.event_date.isoformat(),
                    capacity.station_id,
                    capacity.capacity_units,
                    int(capacity.unavailable),
                ),
            )
            if self._manage_transactions:
                self._conn.commit()

    def get_capacity_day(
        self, event_date: date, station_id: str
    ) -> ProductionStationCapacityDay | None:
        row = self._conn.execute(
            """
            SELECT event_date, station_id, capacity_units, unavailable
            FROM production_station_capacity_days
            WHERE event_date = ? AND station_id = ?
            """,
            (event_date.isoformat(), station_id),
        ).fetchone()
        if row is None:
            return None
        return ProductionStationCapacityDay(
            event_date=date.fromisoformat(str(row[0])),
            station_id=str(row[1]),
            capacity_units=int(row[2]),
            unavailable=bool(row[3]),
        )

    def list_capacity_days(
        self, event_date: date
    ) -> list[ProductionStationCapacityDay]:
        rows = self._conn.execute(
            """
            SELECT event_date, station_id, capacity_units, unavailable
            FROM production_station_capacity_days
            WHERE event_date = ?
            ORDER BY station_id ASC
            """,
            (event_date.isoformat(),),
        ).fetchall()
        return [
            ProductionStationCapacityDay(
                event_date=date.fromisoformat(str(row[0])),
                station_id=str(row[1]),
                capacity_units=int(row[2]),
                unavailable=bool(row[3]),
            )
            for row in rows
        ]
