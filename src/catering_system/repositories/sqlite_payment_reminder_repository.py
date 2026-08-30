"""SQLite adapter for the separate office payment reminder block."""

from __future__ import annotations

import sqlite3
from contextlib import nullcontext
from datetime import date, datetime
from pathlib import Path

from catering_system.domain.order_payment_reminder import (
    OrderPaymentReminder,
    validate_payment_method,
)
from catering_system.repositories.sqlite_migrations import apply_migrations


def _migration_1_create_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS order_payment_reminders (
            order_id TEXT PRIMARY KEY,
            payment_method TEXT NOT NULL,
            invoice_created INTEGER NOT NULL,
            invoice_number TEXT,
            sent_on TEXT,
            due_on TEXT,
            paid_on TEXT,
            cash_received INTEGER NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """CREATE TRIGGER IF NOT EXISTS trg_payment_reminder_owner_insert
        BEFORE INSERT ON order_payment_reminders
        WHEN NOT EXISTS (SELECT 1 FROM orders WHERE order_id = NEW.order_id)
        BEGIN SELECT RAISE(ABORT, 'payment reminder owner does not exist'); END"""
    )
    connection.execute(
        """CREATE TRIGGER IF NOT EXISTS trg_payment_reminder_order_id_update
        BEFORE UPDATE OF order_id ON order_payment_reminders
        WHEN NEW.order_id <> OLD.order_id
        BEGIN SELECT RAISE(ABORT, 'payment reminder owner is immutable'); END"""
    )


def _migration_2_add_quittung_printed(connection: sqlite3.Connection) -> None:
    columns = {
        row[1]
        for row in connection.execute("PRAGMA table_info(order_payment_reminders)")
    }
    if "quittung_printed" not in columns:
        connection.execute(
            "ALTER TABLE order_payment_reminders "
            "ADD COLUMN quittung_printed INTEGER NOT NULL DEFAULT 0"
        )


def _migration_3_add_audit_facts(connection: sqlite3.Connection) -> None:
    columns = {
        row[1]
        for row in connection.execute("PRAGMA table_info(order_payment_reminders)")
    }
    for column in (
        "invoice_created_at",
        "invoice_created_by",
        "invoice_sent_recorded_at",
        "invoice_sent_recorded_by",
        "payment_reminder_sent_at",
        "payment_reminder_sent_by",
        "mahnung_sent_at",
        "mahnung_sent_by",
        "quittung_printed_at",
        "quittung_printed_by",
        "paid_recorded_at",
        "paid_recorded_by",
    ):
        if column not in columns:
            connection.execute(
                f"ALTER TABLE order_payment_reminders ADD COLUMN {column} TEXT"
            )


_MIGRATIONS = (
    (1, "create_order_payment_reminders", _migration_1_create_table),
    (2, "add_quittung_printed", _migration_2_add_quittung_printed),
    (3, "add_payment_audit_facts", _migration_3_add_audit_facts),
)

_SELECT_COLUMNS = """
    order_id,
    payment_method,
    invoice_created,
    invoice_number,
    sent_on,
    due_on,
    paid_on,
    cash_received,
    updated_at,
    quittung_printed,
    invoice_created_at,
    invoice_created_by,
    invoice_sent_recorded_at,
    invoice_sent_recorded_by,
    payment_reminder_sent_at,
    payment_reminder_sent_by,
    mahnung_sent_at,
    mahnung_sent_by,
    quittung_printed_at,
    quittung_printed_by,
    paid_recorded_at,
    paid_recorded_by
"""


def _date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value is not None else None


def _datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value is not None else None


class SQLitePaymentReminderRepository:
    def __init__(self, db_path: str | Path) -> None:
        self._conn = sqlite3.connect(str(db_path))
        self._manage_transactions = True
        try:
            apply_migrations(self._conn, "payment_reminders", _MIGRATIONS)
        except Exception:
            self._conn.close()
            raise

    @classmethod
    def from_connection(
        cls, connection: sqlite3.Connection
    ) -> SQLitePaymentReminderRepository:
        repo = cls.__new__(cls)
        repo._conn = connection
        repo._manage_transactions = False
        apply_migrations(connection, "payment_reminders", _MIGRATIONS)
        return repo

    def _write_scope(self):  # noqa: ANN202
        return self._conn if self._manage_transactions else nullcontext()

    def close(self) -> None:
        self._conn.close()

    def get(self, order_id: str) -> OrderPaymentReminder | None:
        row = self._conn.execute(
            f"SELECT {_SELECT_COLUMNS} FROM order_payment_reminders WHERE order_id = ?",
            (order_id,),
        ).fetchone()
        if row is None:
            return None
        return OrderPaymentReminder(
            order_id=row[0],
            payment_method=validate_payment_method(row[1]),
            invoice_created=bool(row[2]),
            invoice_number=row[3],
            sent_on=_date(row[4]),
            due_on=_date(row[5]),
            paid_on=_date(row[6]),
            cash_received=bool(row[7]),
            updated_at=_datetime(row[8]),
            quittung_printed=bool(row[9]),
            invoice_created_at=_datetime(row[10]),
            invoice_created_by=row[11],
            invoice_sent_recorded_at=_datetime(row[12]),
            invoice_sent_recorded_by=row[13],
            payment_reminder_sent_at=_datetime(row[14]),
            payment_reminder_sent_by=row[15],
            mahnung_sent_at=_datetime(row[16]),
            mahnung_sent_by=row[17],
            quittung_printed_at=_datetime(row[18]),
            quittung_printed_by=row[19],
            paid_recorded_at=_datetime(row[20]),
            paid_recorded_by=row[21],
        )

    def save(self, reminder: OrderPaymentReminder) -> None:
        values = (
            reminder.order_id,
            reminder.payment_method,
            int(reminder.invoice_created),
            reminder.invoice_number,
            reminder.sent_on.isoformat() if reminder.sent_on else None,
            reminder.due_on.isoformat() if reminder.due_on else None,
            reminder.paid_on.isoformat() if reminder.paid_on else None,
            int(reminder.cash_received),
            reminder.updated_at.isoformat() if reminder.updated_at else None,
            int(reminder.quittung_printed),
            reminder.invoice_created_at.isoformat()
            if reminder.invoice_created_at
            else None,
            reminder.invoice_created_by,
            reminder.invoice_sent_recorded_at.isoformat()
            if reminder.invoice_sent_recorded_at
            else None,
            reminder.invoice_sent_recorded_by,
            reminder.payment_reminder_sent_at.isoformat()
            if reminder.payment_reminder_sent_at
            else None,
            reminder.payment_reminder_sent_by,
            reminder.mahnung_sent_at.isoformat() if reminder.mahnung_sent_at else None,
            reminder.mahnung_sent_by,
            reminder.quittung_printed_at.isoformat()
            if reminder.quittung_printed_at
            else None,
            reminder.quittung_printed_by,
            reminder.paid_recorded_at.isoformat()
            if reminder.paid_recorded_at
            else None,
            reminder.paid_recorded_by,
        )
        with self._write_scope():
            self._conn.execute(
                """
                INSERT INTO order_payment_reminders (
                    order_id,
                    payment_method,
                    invoice_created,
                    invoice_number,
                    sent_on,
                    due_on,
                    paid_on,
                    cash_received,
                    updated_at,
                    quittung_printed,
                    invoice_created_at,
                    invoice_created_by,
                    invoice_sent_recorded_at,
                    invoice_sent_recorded_by,
                    payment_reminder_sent_at,
                    payment_reminder_sent_by,
                    mahnung_sent_at,
                    mahnung_sent_by,
                    quittung_printed_at,
                    quittung_printed_by,
                    paid_recorded_at,
                    paid_recorded_by
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                ON CONFLICT(order_id) DO UPDATE SET
                    payment_method = excluded.payment_method,
                    invoice_created = excluded.invoice_created,
                    invoice_number = excluded.invoice_number,
                    sent_on = excluded.sent_on,
                    due_on = excluded.due_on,
                    paid_on = excluded.paid_on,
                    cash_received = excluded.cash_received,
                    updated_at = excluded.updated_at,
                    quittung_printed = excluded.quittung_printed,
                    invoice_created_at = excluded.invoice_created_at,
                    invoice_created_by = excluded.invoice_created_by,
                    invoice_sent_recorded_at = excluded.invoice_sent_recorded_at,
                    invoice_sent_recorded_by = excluded.invoice_sent_recorded_by,
                    payment_reminder_sent_at = excluded.payment_reminder_sent_at,
                    payment_reminder_sent_by = excluded.payment_reminder_sent_by,
                    mahnung_sent_at = excluded.mahnung_sent_at,
                    mahnung_sent_by = excluded.mahnung_sent_by,
                    quittung_printed_at = excluded.quittung_printed_at,
                    quittung_printed_by = excluded.quittung_printed_by,
                    paid_recorded_at = excluded.paid_recorded_at,
                    paid_recorded_by = excluded.paid_recorded_by
                """,
                values,
            )
