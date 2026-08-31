"""Append-only SQLite journal for Courier cash handoff events."""

from __future__ import annotations

import sqlite3
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path

from catering_system.domain.courier_cash_handoff import CourierCashStoredEvent
from catering_system.repositories.sqlite_migrations import apply_migrations

_CREATE = """
CREATE TABLE IF NOT EXISTS courier_cash_events (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    idempotency_key TEXT NOT NULL UNIQUE,
    request_fingerprint TEXT NOT NULL,
    request_json TEXT NOT NULL,
    response_json TEXT NOT NULL,
    order_id TEXT NOT NULL,
    assignment_id TEXT NOT NULL,
    order_version_id TEXT NOT NULL,
    cash_execution_context_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    actor_role TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    from_state TEXT NOT NULL,
    to_state TEXT NOT NULL,
    not_received_reason TEXT,
    note TEXT,
    correction_reason TEXT,
    correction_of_idempotency_key TEXT
)
"""
_INDEXES = (
    """CREATE INDEX IF NOT EXISTS idx_courier_cash_events_order_sequence
       ON courier_cash_events(order_id, sequence DESC)""",
    """CREATE INDEX IF NOT EXISTS idx_courier_cash_events_context_sequence
       ON courier_cash_events(order_id, cash_execution_context_id, sequence DESC)""",
)
_TRIGGERS = (
    """CREATE TRIGGER IF NOT EXISTS trg_courier_cash_events_no_update
       BEFORE UPDATE ON courier_cash_events
       BEGIN SELECT RAISE(ABORT, 'courier cash events are append-only'); END""",
    """CREATE TRIGGER IF NOT EXISTS trg_courier_cash_events_no_delete
       BEFORE DELETE ON courier_cash_events
       BEGIN SELECT RAISE(ABORT, 'courier cash events are append-only'); END""",
    """CREATE TRIGGER IF NOT EXISTS trg_courier_cash_event_owner_insert
       BEFORE INSERT ON courier_cash_events
       WHEN NOT EXISTS (SELECT 1 FROM orders WHERE order_id = NEW.order_id)
       BEGIN SELECT RAISE(ABORT, 'courier cash event owner does not exist'); END""",
)


def _migration_1(connection: sqlite3.Connection) -> None:
    connection.execute(_CREATE)
    for statement in _INDEXES:
        connection.execute(statement)
    for trigger in _TRIGGERS:
        connection.execute(trigger)


_MIGRATIONS = ((1, "create_courier_cash_events", _migration_1),)


def _row(row: sqlite3.Row) -> CourierCashStoredEvent:
    return CourierCashStoredEvent(
        sequence=int(row["sequence"]),
        event_id=row["event_id"],
        idempotency_key=row["idempotency_key"],
        request_fingerprint=row["request_fingerprint"],
        request_json=row["request_json"],
        response_json=row["response_json"],
        order_id=row["order_id"],
        assignment_id=row["assignment_id"],
        order_version_id=row["order_version_id"],
        cash_execution_context_id=row["cash_execution_context_id"],
        event_type=row["event_type"],
        actor_id=row["actor_id"],
        actor_role=row["actor_role"],
        occurred_at=datetime.fromisoformat(row["occurred_at"]),
        recorded_at=datetime.fromisoformat(row["recorded_at"]),
        from_state=row["from_state"],
        to_state=row["to_state"],
        not_received_reason=row["not_received_reason"],
        note=row["note"],
        correction_reason=row["correction_reason"],
        correction_of_idempotency_key=row["correction_of_idempotency_key"],
    )


class SQLiteCourierCashRepository:
    def __init__(self, db_path: str | Path) -> None:
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._manage_transactions = True
        try:
            apply_migrations(self._conn, "courier_cash_handoff", _MIGRATIONS)
        except Exception:
            self._conn.close()
            raise

    @classmethod
    def from_connection(cls, connection: sqlite3.Connection) -> SQLiteCourierCashRepository:
        repo = cls.__new__(cls)
        repo._conn = connection
        repo._conn.row_factory = sqlite3.Row
        repo._manage_transactions = False
        apply_migrations(connection, "courier_cash_handoff", _MIGRATIONS)
        return repo

    def _write_scope(self):  # noqa: ANN202
        return self._conn if self._manage_transactions else nullcontext()

    def close(self) -> None:
        self._conn.close()

    def append_event(self, event: CourierCashStoredEvent) -> None:
        with self._write_scope():
            self._conn.execute(
                """
                INSERT INTO courier_cash_events (
                    event_id, idempotency_key, request_fingerprint, request_json,
                    response_json, order_id, assignment_id, order_version_id,
                    cash_execution_context_id, event_type, actor_id, actor_role,
                    occurred_at, recorded_at, from_state, to_state,
                    not_received_reason, note, correction_reason,
                    correction_of_idempotency_key
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.idempotency_key,
                    event.request_fingerprint,
                    event.request_json,
                    event.response_json,
                    event.order_id,
                    event.assignment_id,
                    event.order_version_id,
                    event.cash_execution_context_id,
                    event.event_type,
                    event.actor_id,
                    event.actor_role,
                    event.occurred_at.isoformat(),
                    event.recorded_at.isoformat(),
                    event.from_state,
                    event.to_state,
                    event.not_received_reason,
                    event.note,
                    event.correction_reason,
                    event.correction_of_idempotency_key,
                ),
            )

    def get_by_idempotency_key(
        self, idempotency_key: str
    ) -> CourierCashStoredEvent | None:
        row = self._conn.execute(
            "SELECT * FROM courier_cash_events WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        return _row(row) if row is not None else None

    def get_latest_for_context(
        self, order_id: str, cash_execution_context_id: str
    ) -> CourierCashStoredEvent | None:
        row = self._conn.execute(
            """
            SELECT * FROM courier_cash_events
            WHERE order_id = ? AND cash_execution_context_id = ?
            ORDER BY sequence DESC LIMIT 1
            """,
            (order_id, cash_execution_context_id),
        ).fetchone()
        return _row(row) if row is not None else None

    def get_latest_for_order(self, order_id: str) -> CourierCashStoredEvent | None:
        row = self._conn.execute(
            """
            SELECT * FROM courier_cash_events
            WHERE order_id = ?
            ORDER BY sequence DESC LIMIT 1
            """,
            (order_id,),
        ).fetchone()
        return _row(row) if row is not None else None

    def get_latest_correction_id(self, order_id: str) -> str | None:
        row = self._conn.execute(
            """
            SELECT event_id FROM courier_cash_events
            WHERE order_id = ? AND event_type = 'BAR_HANDOFF_CORRECTION'
            ORDER BY sequence DESC LIMIT 1
            """,
            (order_id,),
        ).fetchone()
        return str(row[0]) if row is not None else None
