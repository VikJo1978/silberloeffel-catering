"""SQLite adapter for the KI Telefonassistent inbox."""

from __future__ import annotations

import sqlite3
from contextlib import nullcontext
from datetime import date, datetime, time
from pathlib import Path
from typing import cast

from catering_system.domain.ai_telefon_call import (
    AiTelefonCall,
    AiTelefonCallLinkedType,
    AiTelefonCallResultType,
    AiTelefonCallStatus,
    validate_ai_telefon_call,
)
from catering_system.domain.inquiry import FulfillmentMode
from catering_system.repositories.ai_telefon_call_repository import DuplicateAiTelefonCallError
from catering_system.repositories.sqlite_migrations import apply_migrations

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS ai_telefon_calls (
    call_id TEXT PRIMARY KEY,
    strato_id TEXT NOT NULL,
    gmail_message_id TEXT NOT NULL,
    caller_phone TEXT NOT NULL,
    contact_name TEXT NOT NULL,
    email TEXT NOT NULL,
    subject TEXT NOT NULL,
    summary TEXT NOT NULL,
    raw_message TEXT NOT NULL,
    event_type TEXT NOT NULL,
    event_date TEXT,
    event_period TEXT NOT NULL,
    event_start TEXT,
    guest_count INTEGER,
    location TEXT NOT NULL,
    budget_per_person_cents INTEGER,
    fulfillment_mode TEXT NOT NULL,
    customer_request TEXT NOT NULL,
    callback_requested INTEGER,
    callback_date TEXT,
    callback_time TEXT,
    status TEXT NOT NULL,
    result_type TEXT,
    result_id TEXT,
    linked_type TEXT,
    linked_id TEXT,
    received_at TEXT NOT NULL,
    processed_at TEXT,
    updated_at TEXT NOT NULL,
    guest_count_min INTEGER,
    guest_count_max INTEGER,
    CHECK (status IN ('NEW', 'PROCESSED', 'DONE')),
    CHECK (fulfillment_mode IN ('UNKNOWN', 'DELIVERY', 'PICKUP')),
    CHECK (result_type IS NULL OR result_type IN ('INQUIRY', 'TASK', 'LINKED')),
    CHECK (linked_type IS NULL OR linked_type IN ('ORDER', 'INQUIRY', 'OFFER', 'CONTACT')),
    CHECK (callback_requested IS NULL OR callback_requested IN (0, 1))
)
"""

_INDEXES = (
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_ai_telefon_calls_strato_id ON ai_telefon_calls (strato_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_ai_telefon_calls_gmail_message_id ON ai_telefon_calls (gmail_message_id)",
    "CREATE INDEX IF NOT EXISTS idx_ai_telefon_calls_status_received ON ai_telefon_calls (status, received_at DESC)",
)


def _migration_1_create_table(connection: sqlite3.Connection) -> None:
    connection.execute(_CREATE_TABLE)
    for statement in _INDEXES:
        connection.execute(statement)


def _migration_2_guest_range(connection: sqlite3.Connection) -> None:
    columns = {row[1] for row in connection.execute("PRAGMA table_info(ai_telefon_calls)").fetchall()}
    if "guest_count_min" not in columns:
        connection.execute("ALTER TABLE ai_telefon_calls ADD COLUMN guest_count_min INTEGER")
    if "guest_count_max" not in columns:
        connection.execute("ALTER TABLE ai_telefon_calls ADD COLUMN guest_count_max INTEGER")


_MIGRATIONS = (
    (1, "create_ai_telefon_calls", _migration_1_create_table),
    (2, "add_guest_count_range", _migration_2_guest_range),
)


class SQLiteAiTelefonCallRepository:
    def __init__(self, db_path: str | Path) -> None:
        self._conn = sqlite3.connect(str(db_path))
        self._manage_transactions = True
        try:
            apply_migrations(self._conn, "ai_telefon_calls", _MIGRATIONS)
        except Exception:
            self._conn.close()
            raise

    @classmethod
    def from_connection(cls, connection: sqlite3.Connection) -> "SQLiteAiTelefonCallRepository":
        repo = cls.__new__(cls)
        repo._conn = connection
        repo._manage_transactions = False
        apply_migrations(connection, "ai_telefon_calls", _MIGRATIONS)
        return repo

    def _write_scope(self):
        return self._conn if self._manage_transactions else nullcontext()

    def close(self) -> None:
        self._conn.close()

    def get(self, call_id: str) -> AiTelefonCall | None:
        row = self._conn.execute("SELECT * FROM ai_telefon_calls WHERE call_id = ?", (call_id,)).fetchone()
        return _row_to_call(row) if row else None

    def find_by_strato_id(self, strato_id: str) -> AiTelefonCall | None:
        row = self._conn.execute("SELECT * FROM ai_telefon_calls WHERE strato_id = ?", (strato_id.strip(),)).fetchone()
        return _row_to_call(row) if row else None

    def find_by_gmail_message_id(self, gmail_message_id: str) -> AiTelefonCall | None:
        row = self._conn.execute(
            "SELECT * FROM ai_telefon_calls WHERE gmail_message_id = ?",
            (gmail_message_id.strip(),),
        ).fetchone()
        return _row_to_call(row) if row else None

    def save(self, call: AiTelefonCall) -> None:
        validated = validate_ai_telefon_call(call)
        try:
            with self._write_scope():
                self._conn.execute(
                    """
                    INSERT INTO ai_telefon_calls (
                        call_id, strato_id, gmail_message_id, caller_phone,
                        contact_name, email, subject, summary, raw_message,
                        event_type, event_date, event_period, event_start,
                        guest_count, location, budget_per_person_cents,
                        fulfillment_mode, customer_request, callback_requested,
                        callback_date, callback_time, status, result_type,
                        result_id, linked_type, linked_id, received_at,
                        processed_at, updated_at, guest_count_min, guest_count_max
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    _values(validated),
                )
        except sqlite3.IntegrityError as exc:
            raise DuplicateAiTelefonCallError(
                "STRATO or Gmail message already exists in KI Telefonassistent inbox"
            ) from exc

    def update(self, call: AiTelefonCall) -> None:
        validated = validate_ai_telefon_call(call)
        try:
            with self._write_scope():
                updated = self._conn.execute(
                    """
                    UPDATE ai_telefon_calls SET
                        strato_id = ?, gmail_message_id = ?, caller_phone = ?,
                        contact_name = ?, email = ?, subject = ?, summary = ?,
                        raw_message = ?, event_type = ?, event_date = ?,
                        event_period = ?, event_start = ?, guest_count = ?,
                        location = ?, budget_per_person_cents = ?,
                        fulfillment_mode = ?, customer_request = ?,
                        callback_requested = ?, callback_date = ?, callback_time = ?,
                        status = ?, result_type = ?, result_id = ?, linked_type = ?,
                        linked_id = ?, received_at = ?, processed_at = ?, updated_at = ?,
                        guest_count_min = ?, guest_count_max = ?
                    WHERE call_id = ?
                    """,
                    _values(validated)[1:] + (validated.call_id,),
                ).rowcount
                if updated != 1:
                    raise KeyError(validated.call_id)
        except sqlite3.IntegrityError as exc:
            raise DuplicateAiTelefonCallError(
                "STRATO or Gmail message already exists in KI Telefonassistent inbox"
            ) from exc

    def list_recent(self, *, limit: int = 100) -> list[AiTelefonCall]:
        if limit < 1:
            return []
        rows = self._conn.execute(
            "SELECT * FROM ai_telefon_calls ORDER BY received_at DESC, call_id DESC LIMIT ?",
            (min(limit, 500),),
        ).fetchall()
        return [_row_to_call(row) for row in rows]

    def count_new(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM ai_telefon_calls WHERE status = 'NEW'").fetchone()
        return int(row[0]) if row else 0


def _values(call: AiTelefonCall) -> tuple[object, ...]:
    return (
        call.call_id,
        call.strato_id,
        call.gmail_message_id,
        call.caller_phone,
        call.contact_name,
        call.email,
        call.subject,
        call.summary,
        call.raw_message,
        call.event_type,
        call.event_date.isoformat() if call.event_date else None,
        call.event_period,
        call.event_start.isoformat(timespec="minutes") if call.event_start else None,
        call.guest_count,
        call.location,
        call.budget_per_person_cents,
        call.fulfillment_mode,
        call.customer_request,
        None if call.callback_requested is None else int(call.callback_requested),
        call.callback_date.isoformat() if call.callback_date else None,
        call.callback_time.isoformat(timespec="minutes") if call.callback_time else None,
        call.status,
        call.result_type,
        call.result_id,
        call.linked_type,
        call.linked_id,
        call.received_at.isoformat() if call.received_at else None,
        call.processed_at.isoformat() if call.processed_at else None,
        call.updated_at.isoformat() if call.updated_at else None,
        call.guest_count_min,
        call.guest_count_max,
    )


def _row_to_call(row: tuple[object, ...]) -> AiTelefonCall:
    callback_raw = row[18]
    return validate_ai_telefon_call(
        AiTelefonCall(
            call_id=cast(str, row[0]),
            strato_id=cast(str, row[1]),
            gmail_message_id=cast(str, row[2]),
            caller_phone=cast(str, row[3]),
            contact_name=cast(str, row[4]),
            email=cast(str, row[5]),
            subject=cast(str, row[6]),
            summary=cast(str, row[7]),
            raw_message=cast(str, row[8]),
            event_type=cast(str, row[9]),
            event_date=date.fromisoformat(cast(str, row[10])) if row[10] else None,
            event_period=cast(str, row[11]),
            event_start=time.fromisoformat(cast(str, row[12])) if row[12] else None,
            guest_count=cast(int | None, row[13]),
            location=cast(str, row[14]),
            budget_per_person_cents=cast(int | None, row[15]),
            fulfillment_mode=cast(FulfillmentMode, row[16]),
            customer_request=cast(str, row[17]),
            callback_requested=None if callback_raw is None else bool(callback_raw),
            callback_date=date.fromisoformat(cast(str, row[19])) if row[19] else None,
            callback_time=time.fromisoformat(cast(str, row[20])) if row[20] else None,
            status=cast(AiTelefonCallStatus, row[21]),
            result_type=cast(AiTelefonCallResultType | None, row[22]),
            result_id=cast(str | None, row[23]),
            linked_type=cast(AiTelefonCallLinkedType | None, row[24]),
            linked_id=cast(str | None, row[25]),
            received_at=datetime.fromisoformat(cast(str, row[26])),
            processed_at=datetime.fromisoformat(cast(str, row[27])) if row[27] else None,
            updated_at=datetime.fromisoformat(cast(str, row[28])),
            guest_count_min=cast(int | None, row[29]) if len(row) > 29 else None,
            guest_count_max=cast(int | None, row[30]) if len(row) > 30 else None,
        )
    )
