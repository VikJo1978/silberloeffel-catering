"""SQLite order repository — same OrderRepository Protocol as the in-memory baseline.

Persistence adapter only: no business rules, no new truth axis. Schema mirrors
the frozen Order/OrderVersion field set (incl. the two OPERATIONAL_CORE §7 fields).
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import cast

from catering_system.domain.inquiry import PlanningMode, validate_planning_mode
from catering_system.domain.order import Order, OrderVersion

_SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    order_id TEXT PRIMARY KEY,
    source_inquiry_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    candidate_order_version_id TEXT,
    effective_order_version_id TEXT,
    cancelled_at TEXT
);
CREATE TABLE IF NOT EXISTS order_versions (
    order_version_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    version_number INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    event_date TEXT NOT NULL,
    time_window_text TEXT NOT NULL,
    location_text TEXT NOT NULL,
    guest_count_estimate INTEGER,
    planning_mode TEXT NOT NULL,
    kitchen_print_confirmed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_order_versions_order_id
    ON order_versions (order_id, version_number);
"""

_UNIQUE_VERSION_NUMBER_INDEX = """
CREATE UNIQUE INDEX IF NOT EXISTS uq_order_versions_order_version_number
    ON order_versions (order_id, version_number);
"""


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


class SQLiteOrderRepository:
    def __init__(self, db_path: str | Path) -> None:
        self._conn = sqlite3.connect(str(db_path))
        self._conn.executescript(_SCHEMA)
        # STORNO pack §4: defensive in-place migration for pre-Storno databases.
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(orders)").fetchall()}
        if "cancelled_at" not in cols:
            self._conn.execute("ALTER TABLE orders ADD COLUMN cancelled_at TEXT")
        duplicate = self._conn.execute(
            "SELECT order_id, version_number FROM order_versions "
            "GROUP BY order_id, version_number HAVING COUNT(*) > 1 LIMIT 1"
        ).fetchone()
        if duplicate is not None:
            self._conn.close()
            raise ValueError(
                "cannot enforce unique order version numbers: duplicate "
                f"version_number {duplicate[1]} for order {duplicate[0]!r}"
            )
        self._conn.execute(_UNIQUE_VERSION_NUMBER_INDEX)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def save_order_with_initial_version(
        self, order: Order, version: OrderVersion
    ) -> None:
        """Create the aggregate root and v1 in one SQLite transaction."""
        if version.order_id != order.order_id or version.version_number != 1:
            raise ValueError("initial version must be v1 of the supplied order")
        with self._conn:
            self._conn.execute(
                "INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?)",
                self._order_values(order),
            )
            self._conn.execute(
                "INSERT INTO order_versions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                self._version_values(version),
            )

    def get_order(self, order_id: str) -> Order | None:
        row = self._conn.execute(
            "SELECT * FROM orders WHERE order_id = ?", (order_id,)
        ).fetchone()
        if row is None:
            return None
        return Order(
            order_id=row[0],
            source_inquiry_id=row[1],
            created_at=_dt(row[2]),
            updated_at=_dt(row[3]),
            candidate_order_version_id=row[4],
            effective_order_version_id=row[5],
            cancelled_at=_dt(row[6]) if row[6] is not None else None,
        )

    def update_order(self, order: Order) -> None:
        with self._conn:
            updated = self._update_order_row(order)
            if updated != 1:
                raise KeyError(order.order_id)

    def list_orders(self) -> list[Order]:
        rows = self._conn.execute("SELECT * FROM orders ORDER BY order_id").fetchall()
        return [
            Order(
                order_id=r[0],
                source_inquiry_id=r[1],
                created_at=_dt(r[2]),
                updated_at=_dt(r[3]),
                candidate_order_version_id=r[4],
                effective_order_version_id=r[5],
                cancelled_at=_dt(r[6]) if r[6] is not None else None,
            )
            for r in rows
        ]

    def append_order_version(self, order: Order, version: OrderVersion) -> None:
        """Append a version and update its aggregate root in one transaction."""
        if version.order_id != order.order_id or version.version_number < 1:
            raise ValueError("version must belong to the supplied order")
        with self._conn:
            updated = self._update_order_row(order)
            if updated != 1:
                raise KeyError(order.order_id)
            self._conn.execute(
                "INSERT INTO order_versions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                self._version_values(version),
            )

    def update_order_version(self, version: OrderVersion) -> None:
        with self._conn:
            updated = self._conn.execute(
                """
                UPDATE order_versions SET
                    order_id = ?, version_number = ?, created_at = ?,
                    event_date = ?, time_window_text = ?, location_text = ?,
                    guest_count_estimate = ?, planning_mode = ?,
                    kitchen_print_confirmed_at = ?
                WHERE order_version_id = ?
                """,
                self._version_values(version)[1:] + (version.order_version_id,),
            ).rowcount
            if updated != 1:
                raise KeyError(version.order_version_id)

    def _update_order_row(self, order: Order) -> int:
        return self._conn.execute(
            """
            UPDATE orders SET
                source_inquiry_id = ?, created_at = ?, updated_at = ?,
                candidate_order_version_id = ?, effective_order_version_id = ?,
                cancelled_at = ?
            WHERE order_id = ?
            """,
            self._order_values(order)[1:] + (order.order_id,),
        ).rowcount

    @staticmethod
    def _order_values(order: Order) -> tuple:
        return (
            order.order_id,
            order.source_inquiry_id,
            order.created_at.isoformat(),
            order.updated_at.isoformat(),
            order.candidate_order_version_id,
            order.effective_order_version_id,
            order.cancelled_at.isoformat() if order.cancelled_at is not None else None,
        )

    @staticmethod
    def _version_values(version: OrderVersion) -> tuple:
        return (
            version.order_version_id,
            version.order_id,
            version.version_number,
            version.created_at.isoformat(),
            version.event_date.isoformat(),
            version.time_window_text,
            version.location_text,
            version.guest_count_estimate,
            version.planning_mode,
            version.kitchen_print_confirmed_at.isoformat()
            if version.kitchen_print_confirmed_at is not None
            else None,
        )

    def get_order_version(self, order_version_id: str) -> OrderVersion | None:
        row = self._conn.execute(
            "SELECT * FROM order_versions WHERE order_version_id = ?",
            (order_version_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_version(row)

    def list_order_versions(self, order_id: str) -> list[OrderVersion]:
        rows = self._conn.execute(
            "SELECT * FROM order_versions WHERE order_id = ? ORDER BY version_number",
            (order_id,),
        ).fetchall()
        return [self._row_to_version(r) for r in rows]

    @staticmethod
    def _row_to_version(row: tuple) -> OrderVersion:
        return OrderVersion(
            order_version_id=row[0],
            order_id=row[1],
            version_number=row[2],
            created_at=_dt(row[3]),
            event_date=date.fromisoformat(row[4]),
            time_window_text=row[5],
            location_text=row[6],
            guest_count_estimate=row[7],
            planning_mode=cast(PlanningMode, validate_planning_mode(row[8])),
            kitchen_print_confirmed_at=_dt(row[9]) if row[9] is not None else None,
        )
