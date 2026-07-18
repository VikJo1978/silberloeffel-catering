"""SQLite adapter for append-only order operational PAUSE events."""

from __future__ import annotations

import sqlite3
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path

from catering_system.domain.order_operational_pause import (
    OrderOperationalPauseEvent,
    derive_active_pause,
)
from catering_system.repositories.sqlite_migrations import apply_migrations

_CREATE_EVENTS = """
CREATE TABLE IF NOT EXISTS order_operational_pause_events (
    pause_event_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('paused', 'resumed')),
    reason_code TEXT NOT NULL,
    note TEXT,
    actor_reference TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    command_id TEXT NOT NULL UNIQUE,
    resumes_pause_event_id TEXT,
    FOREIGN KEY (order_id) REFERENCES orders(order_id)
)
"""

_CREATE_INDEX = """
CREATE INDEX IF NOT EXISTS idx_order_operational_pause_events_order_occurred
    ON order_operational_pause_events (order_id, occurred_at)
"""

_APPEND_ONLY_TRIGGERS = (
    """CREATE TRIGGER IF NOT EXISTS trg_order_operational_pause_events_no_update
    BEFORE UPDATE ON order_operational_pause_events
    BEGIN SELECT RAISE(ABORT, 'order operational pause events are append-only'); END""",
    """CREATE TRIGGER IF NOT EXISTS trg_order_operational_pause_events_no_delete
    BEFORE DELETE ON order_operational_pause_events
    BEGIN SELECT RAISE(ABORT, 'order operational pause events are append-only'); END""",
    """CREATE TRIGGER IF NOT EXISTS trg_order_operational_pause_owner_insert
    BEFORE INSERT ON order_operational_pause_events
    WHEN NOT EXISTS (SELECT 1 FROM orders WHERE order_id = NEW.order_id)
    BEGIN SELECT RAISE(ABORT, 'pause event owner does not exist'); END""",
)


def _migration_1_create_pause_events(connection: sqlite3.Connection) -> None:
    connection.execute(_CREATE_EVENTS)
    connection.execute(_CREATE_INDEX)
    for trigger in _APPEND_ONLY_TRIGGERS:
        connection.execute(trigger)


_MIGRATIONS = ((1, "create_order_operational_pause_events", _migration_1_create_pause_events),)


def _row_to_event(row: sqlite3.Row) -> OrderOperationalPauseEvent:
    return OrderOperationalPauseEvent(
        pause_event_id=row["pause_event_id"],
        order_id=row["order_id"],
        action=row["action"],
        reason_code=row["reason_code"],
        note=row["note"],
        actor_reference=row["actor_reference"],
        occurred_at=datetime.fromisoformat(row["occurred_at"]),
        command_id=row["command_id"],
        resumes_pause_event_id=row["resumes_pause_event_id"],
    )


class SQLiteOrderOperationalPauseRepository:
    def __init__(self, db_path: str | Path) -> None:
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._manage_transactions = True
        try:
            apply_migrations(self._conn, "order_operational_pause", _MIGRATIONS)
        except Exception:
            self._conn.close()
            raise

    @classmethod
    def from_connection(
        cls, connection: sqlite3.Connection
    ) -> SQLiteOrderOperationalPauseRepository:
        repo = cls.__new__(cls)
        repo._conn = connection
        repo._conn.row_factory = sqlite3.Row
        repo._manage_transactions = False
        apply_migrations(connection, "order_operational_pause", _MIGRATIONS)
        return repo

    def _write_scope(self):  # noqa: ANN202
        return self._conn if self._manage_transactions else nullcontext()

    def close(self) -> None:
        self._conn.close()

    def append_event(self, event: OrderOperationalPauseEvent) -> None:
        with self._write_scope():
            self._conn.execute(
                """
                INSERT INTO order_operational_pause_events (
                    pause_event_id,
                    order_id,
                    action,
                    reason_code,
                    note,
                    actor_reference,
                    occurred_at,
                    command_id,
                    resumes_pause_event_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.pause_event_id,
                    event.order_id,
                    event.action,
                    event.reason_code,
                    event.note,
                    event.actor_reference,
                    event.occurred_at.isoformat(),
                    event.command_id,
                    event.resumes_pause_event_id,
                ),
            )

    def list_events(self, order_id: str) -> tuple[OrderOperationalPauseEvent, ...]:
        rows = self._conn.execute(
            """
            SELECT pause_event_id, order_id, action, reason_code, note,
                   actor_reference, occurred_at, command_id, resumes_pause_event_id
            FROM order_operational_pause_events
            WHERE order_id = ?
            ORDER BY occurred_at ASC, pause_event_id ASC
            """,
            (order_id,),
        ).fetchall()
        return tuple(_row_to_event(row) for row in rows)

    def get_active_pause(self, order_id: str) -> OrderOperationalPauseEvent | None:
        return derive_active_pause(self.list_events(order_id))
