"""SQLite catalog repository — read model tables for 6D-1."""

from __future__ import annotations

import json
import sqlite3
from contextlib import nullcontext
from datetime import date, datetime
from pathlib import Path

from catering_system.domain.catalog import (
    CatalogDish,
    CatalogDishNotFoundError,
    CatalogDishStaleError,
    CatalogPriceHistoryEntry,
    validate_allergen_codes,
)
from catering_system.repositories.sqlite_migrations import apply_migrations


def _migration_1_create_catalog_tables(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS catalog_dishes (
            dish_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            composition TEXT,
            notes TEXT,
            current_unit_net_cents INTEGER NOT NULL,
            allergens_json TEXT NOT NULL,
            active INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_catalog_dishes_active_name
        ON catalog_dishes (active, name)
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS catalog_price_history (
            entry_id TEXT PRIMARY KEY,
            dish_id TEXT NOT NULL,
            old_unit_net_cents INTEGER,
            new_unit_net_cents INTEGER NOT NULL,
            changed_at TEXT NOT NULL,
            changed_by TEXT NOT NULL,
            effective_from TEXT,
            FOREIGN KEY (dish_id) REFERENCES catalog_dishes (dish_id)
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_catalog_price_history_dish_changed
        ON catalog_price_history (dish_id, changed_at DESC)
        """
    )


_MIGRATIONS = ((1, "catalog_dishes_v1", _migration_1_create_catalog_tables),)


class SQLiteCatalogRepository:
    def __init__(self, db_path: str | Path) -> None:
        self._conn = sqlite3.connect(str(db_path))
        self._manage_transactions = True
        try:
            apply_migrations(self._conn, "catalog", _MIGRATIONS)
        except Exception:
            self._conn.close()
            raise

    @classmethod
    def from_connection(cls, connection: sqlite3.Connection) -> SQLiteCatalogRepository:
        repo = cls.__new__(cls)
        repo._conn = connection
        repo._manage_transactions = False
        apply_migrations(connection, "catalog", _MIGRATIONS)
        return repo

    def _write_scope(self):  # noqa: ANN202
        return self._conn if self._manage_transactions else nullcontext()

    def close(self) -> None:
        self._conn.close()

    def list_dishes(
        self,
        *,
        active_only: bool = False,
        q: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[CatalogDish]:
        where, params = self._filters(active_only=active_only, q=q)
        rows = self._conn.execute(
            f"""
            SELECT dish_id, name, description, composition, notes,
                   current_unit_net_cents, allergens_json, active,
                   created_at, updated_at
            FROM catalog_dishes
            {where}
            ORDER BY active DESC, name COLLATE NOCASE ASC, dish_id ASC
            LIMIT ? OFFSET ?
            """,
            (*params, limit, offset),
        ).fetchall()
        return [_row_to_dish(row) for row in rows]

    def count_dishes(
        self,
        *,
        active_only: bool = False,
        q: str | None = None,
    ) -> int:
        where, params = self._filters(active_only=active_only, q=q)
        row = self._conn.execute(
            f"SELECT COUNT(*) FROM catalog_dishes {where}",
            params,
        ).fetchone()
        assert row is not None
        return int(row[0])

    def get_dish(self, dish_id: str) -> CatalogDish | None:
        row = self._conn.execute(
            """
            SELECT dish_id, name, description, composition, notes,
                   current_unit_net_cents, allergens_json, active,
                   created_at, updated_at
            FROM catalog_dishes
            WHERE dish_id = ?
            """,
            (dish_id,),
        ).fetchone()
        if row is None:
            return None
        return _row_to_dish(row)

    def list_price_history(
        self, dish_id: str, *, limit: int = 20
    ) -> list[CatalogPriceHistoryEntry]:
        rows = self._conn.execute(
            """
            SELECT entry_id, dish_id, old_unit_net_cents, new_unit_net_cents,
                   changed_at, changed_by, effective_from
            FROM catalog_price_history
            WHERE dish_id = ?
            ORDER BY changed_at DESC, entry_id ASC
            LIMIT ?
            """,
            (dish_id, limit),
        ).fetchall()
        return [_row_to_history(row) for row in rows]

    def insert_dish_if_absent(self, dish: CatalogDish) -> bool:
        with self._write_scope():
            cursor = self._conn.execute(
                "SELECT 1 FROM catalog_dishes WHERE dish_id = ?",
                (dish.dish_id,),
            )
            if cursor.fetchone() is not None:
                return False
            self._conn.execute(
                """
                INSERT INTO catalog_dishes (
                    dish_id, name, description, composition, notes,
                    current_unit_net_cents, allergens_json, active,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    dish.dish_id,
                    dish.name,
                    dish.description,
                    dish.composition,
                    dish.notes,
                    dish.current_unit_net_cents,
                    json.dumps(list(dish.allergens)),
                    int(dish.active),
                    dish.created_at.isoformat(),
                    dish.updated_at.isoformat(),
                ),
            )
            if self._manage_transactions:
                self._conn.commit()
        return True

    def update_dish(
        self,
        dish: CatalogDish,
        *,
        expected_updated_at: datetime,
        price_history_entry: CatalogPriceHistoryEntry | None = None,
    ) -> None:
        with self._write_scope():
            row = self._conn.execute(
                """
                SELECT updated_at FROM catalog_dishes WHERE dish_id = ?
                """,
                (dish.dish_id,),
            ).fetchone()
            if row is None:
                raise CatalogDishNotFoundError(dish.dish_id)
            stored_at = datetime.fromisoformat(str(row[0]))
            if stored_at != expected_updated_at:
                raise CatalogDishStaleError(dish.dish_id)
            self._conn.execute(
                """
                UPDATE catalog_dishes
                SET name = ?, description = ?, composition = ?, notes = ?,
                    current_unit_net_cents = ?, allergens_json = ?, active = ?,
                    updated_at = ?
                WHERE dish_id = ?
                """,
                (
                    dish.name,
                    dish.description,
                    dish.composition,
                    dish.notes,
                    dish.current_unit_net_cents,
                    json.dumps(list(dish.allergens)),
                    int(dish.active),
                    dish.updated_at.isoformat(),
                    dish.dish_id,
                ),
            )
            if price_history_entry is not None:
                self._conn.execute(
                    """
                    INSERT INTO catalog_price_history (
                        entry_id, dish_id, old_unit_net_cents, new_unit_net_cents,
                        changed_at, changed_by, effective_from
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        price_history_entry.entry_id,
                        price_history_entry.dish_id,
                        price_history_entry.old_unit_net_cents,
                        price_history_entry.new_unit_net_cents,
                        price_history_entry.changed_at.isoformat(),
                        price_history_entry.changed_by,
                        (
                            price_history_entry.effective_from.isoformat()
                            if price_history_entry.effective_from is not None
                            else None
                        ),
                    ),
                )
            if self._manage_transactions:
                self._conn.commit()

    @staticmethod
    def _filters(*, active_only: bool, q: str | None) -> tuple[str, list[object]]:
        clauses: list[str] = []
        params: list[object] = []
        if active_only:
            clauses.append("active = 1")
        if q:
            clauses.append("name LIKE ? ESCAPE '\\'")
            params.append(f"%{_escape_like(q)}%")
        if not clauses:
            return "", params
        return "WHERE " + " AND ".join(clauses), params


def _optional_sql_text(value: object) -> str | None:
    return None if value is None else str(value)


def _sql_int(value: object) -> int:
    if isinstance(value, int):
        return value
    return int(str(value))


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _row_to_dish(row: tuple[object, ...]) -> CatalogDish:
    allergens_raw = json.loads(str(row[6]))
    if not isinstance(allergens_raw, list):
        raise ValueError("allergens_json must decode to a list")
    return CatalogDish(
        dish_id=str(row[0]),
        name=str(row[1]),
        description=_optional_sql_text(row[2]),
        composition=_optional_sql_text(row[3]),
        notes=_optional_sql_text(row[4]),
        current_unit_net_cents=_sql_int(row[5]),
        allergens=validate_allergen_codes(allergens_raw),
        active=bool(row[7]),
        created_at=datetime.fromisoformat(str(row[8])),
        updated_at=datetime.fromisoformat(str(row[9])),
    )


def _row_to_history(row: tuple[object, ...]) -> CatalogPriceHistoryEntry:
    effective_raw = row[6]
    return CatalogPriceHistoryEntry(
        entry_id=str(row[0]),
        dish_id=str(row[1]),
        old_unit_net_cents=_sql_int(row[2]) if row[2] is not None else None,
        new_unit_net_cents=_sql_int(row[3]),
        changed_at=datetime.fromisoformat(str(row[4])),
        changed_by=str(row[5]),
        effective_from=date.fromisoformat(str(effective_raw))
        if effective_raw is not None
        else None,
    )
