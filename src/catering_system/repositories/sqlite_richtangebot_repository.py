"""SQLite persistence for non-binding Richtangebote."""

from __future__ import annotations

import sqlite3
from contextlib import nullcontext
from datetime import date, datetime, time
from pathlib import Path
from typing import cast

from catering_system.domain.richtangebot import (
    Richtangebot,
    RichtangebotStatus,
    validate_richtangebot,
)
from catering_system.repositories.sqlite_migrations import apply_migrations

_CREATE = """
CREATE TABLE IF NOT EXISTS richtangebote (
    richtangebot_id TEXT PRIMARY KEY,
    source_call_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    contact_name TEXT NOT NULL,
    caller_phone TEXT NOT NULL,
    email TEXT NOT NULL,
    event_type TEXT NOT NULL,
    event_date TEXT,
    event_date_text TEXT NOT NULL,
    event_start TEXT,
    event_time_text TEXT NOT NULL,
    guest_count INTEGER,
    guest_count_min INTEGER,
    guest_count_max INTEGER,
    location TEXT NOT NULL,
    budget_per_person_cents INTEGER,
    budget_total_cents INTEGER,
    customer_request TEXT NOT NULL,
    disclaimer TEXT NOT NULL,
    status TEXT NOT NULL,
    CHECK (status IN ('DRAFT', 'SUPERSEDED', 'CLOSED'))
)
"""

_INDEXES = (
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_richtangebote_source_call ON richtangebote (source_call_id)",
    "CREATE INDEX IF NOT EXISTS idx_richtangebote_created ON richtangebote (created_at DESC)",
)


def _migration_1(connection: sqlite3.Connection) -> None:
    connection.execute(_CREATE)
    for statement in _INDEXES:
        connection.execute(statement)


_MIGRATIONS = ((1, "create_richtangebote", _migration_1),)


class SQLiteRichtangebotRepository:
    def __init__(self, db_path: str | Path) -> None:
        self._conn = sqlite3.connect(str(db_path))
        self._manage_transactions = True
        try:
            apply_migrations(self._conn, "richtangebote", _MIGRATIONS)
        except Exception:
            self._conn.close()
            raise

    @classmethod
    def from_connection(
        cls, connection: sqlite3.Connection
    ) -> "SQLiteRichtangebotRepository":
        repo = cls.__new__(cls)
        repo._conn = connection
        repo._manage_transactions = False
        apply_migrations(connection, "richtangebote", _MIGRATIONS)
        return repo

    def _scope(self):
        return self._conn if self._manage_transactions else nullcontext()

    def close(self) -> None:
        self._conn.close()

    def get(self, richtangebot_id: str) -> Richtangebot | None:
        row = self._conn.execute(
            "SELECT * FROM richtangebote WHERE richtangebot_id = ?", (richtangebot_id,)
        ).fetchone()
        return _row(row) if row else None

    def find_by_source_call_id(self, source_call_id: str) -> Richtangebot | None:
        row = self._conn.execute(
            "SELECT * FROM richtangebote WHERE source_call_id = ?", (source_call_id,)
        ).fetchone()
        return _row(row) if row else None

    def save(self, value: Richtangebot) -> None:
        item = validate_richtangebot(value)
        with self._scope():
            self._conn.execute(
                """
                INSERT INTO richtangebote (
                    richtangebot_id, source_call_id, created_at, updated_at,
                    contact_name, caller_phone, email, event_type, event_date,
                    event_date_text, event_start, event_time_text, guest_count,
                    guest_count_min, guest_count_max, location,
                    budget_per_person_cents, budget_total_cents, customer_request,
                    disclaimer, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                _values(item),
            )

    def update(self, value: Richtangebot) -> None:
        item = validate_richtangebot(value)
        with self._scope():
            count = self._conn.execute(
                """
                UPDATE richtangebote SET
                    source_call_id = ?, created_at = ?, updated_at = ?,
                    contact_name = ?, caller_phone = ?, email = ?, event_type = ?,
                    event_date = ?, event_date_text = ?, event_start = ?,
                    event_time_text = ?, guest_count = ?, guest_count_min = ?,
                    guest_count_max = ?, location = ?, budget_per_person_cents = ?,
                    budget_total_cents = ?, customer_request = ?, disclaimer = ?,
                    status = ?
                WHERE richtangebot_id = ?
                """,
                _values(item)[1:] + (item.richtangebot_id,),
            ).rowcount
            if count != 1:
                raise KeyError(item.richtangebot_id)

    def list_recent(self, *, limit: int = 100) -> list[Richtangebot]:
        if limit < 1:
            return []
        rows = self._conn.execute(
            "SELECT * FROM richtangebote ORDER BY created_at DESC, richtangebot_id DESC LIMIT ?",
            (min(limit, 500),),
        ).fetchall()
        return [_row(row) for row in rows]


def _values(item: Richtangebot) -> tuple[object, ...]:
    return (
        item.richtangebot_id,
        item.source_call_id,
        item.created_at.isoformat(),
        item.updated_at.isoformat(),
        item.contact_name,
        item.caller_phone,
        item.email,
        item.event_type,
        item.event_date.isoformat() if item.event_date else None,
        item.event_date_text,
        item.event_start.isoformat(timespec="minutes") if item.event_start else None,
        item.event_time_text,
        item.guest_count,
        item.guest_count_min,
        item.guest_count_max,
        item.location,
        item.budget_per_person_cents,
        item.budget_total_cents,
        item.customer_request,
        item.disclaimer,
        item.status,
    )


def _row(row: tuple[object, ...]) -> Richtangebot:
    return validate_richtangebot(
        Richtangebot(
            richtangebot_id=cast(str, row[0]),
            source_call_id=cast(str, row[1]),
            created_at=datetime.fromisoformat(cast(str, row[2])),
            updated_at=datetime.fromisoformat(cast(str, row[3])),
            contact_name=cast(str, row[4]),
            caller_phone=cast(str, row[5]),
            email=cast(str, row[6]),
            event_type=cast(str, row[7]),
            event_date=date.fromisoformat(cast(str, row[8])) if row[8] else None,
            event_date_text=cast(str, row[9]),
            event_start=time.fromisoformat(cast(str, row[10])) if row[10] else None,
            event_time_text=cast(str, row[11]),
            guest_count=cast(int | None, row[12]),
            guest_count_min=cast(int | None, row[13]),
            guest_count_max=cast(int | None, row[14]),
            location=cast(str, row[15]),
            budget_per_person_cents=cast(int | None, row[16]),
            budget_total_cents=cast(int | None, row[17]),
            customer_request=cast(str, row[18]),
            disclaimer=cast(str, row[19]),
            status=cast(RichtangebotStatus, row[20]),
        )
    )
