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
    effective_order_version_id TEXT
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


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


class SQLiteOrderRepository:
    def __init__(self, db_path: str | Path) -> None:
        self._conn = sqlite3.connect(str(db_path))
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def save_order(self, order: Order) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO orders VALUES (?, ?, ?, ?, ?, ?)",
            (
                order.order_id,
                order.source_inquiry_id,
                order.created_at.isoformat(),
                order.updated_at.isoformat(),
                order.candidate_order_version_id,
                order.effective_order_version_id,
            ),
        )
        self._conn.commit()

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
        )

    def update_order(self, order: Order) -> None:
        if self.get_order(order.order_id) is None:
            raise KeyError(order.order_id)
        self.save_order(order)

    def save_order_version(self, version: OrderVersion) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO order_versions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
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
            ),
        )
        self._conn.commit()

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
