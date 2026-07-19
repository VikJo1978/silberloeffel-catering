"""SQLite PhoneContactPoint repository."""

from __future__ import annotations

import sqlite3
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path
from catering_system.domain.customer_identity import (
    ACTIVE_CUSTOMER_IDENTITY_STATUS,
    ACTIVE_PHONE_CONTACT_POINT_STATUS,
    PhoneContactPoint,
    validate_phone_contact_point,
    validate_phone_contact_point_status,
)
from catering_system.domain.phone_normalization import normalize_phone_for_contact_point
from catering_system.repositories.sqlite_migrations import apply_migrations

_CREATE_PHONE_CONTACT_POINTS = """
CREATE TABLE IF NOT EXISTS phone_contact_points (
    phone_contact_point_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    normalized_phone TEXT NOT NULL,
    display_phone TEXT,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    valid_from TEXT,
    valid_to TEXT,
    FOREIGN KEY (customer_id) REFERENCES customer_identities (customer_id)
);
"""

_PHONE_INDEXES = (
    """
    CREATE INDEX IF NOT EXISTS idx_phone_contact_points_customer_id
        ON phone_contact_points (customer_id);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_phone_contact_points_normalized_phone
        ON phone_contact_points (normalized_phone);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_phone_contact_points_status
        ON phone_contact_points (status);
    """,
)

_IMMUTABLE_OWNER_TRIGGERS = (
    """
    CREATE TRIGGER IF NOT EXISTS trg_phone_contact_point_owner_insert
    BEFORE INSERT ON phone_contact_points
    WHEN NOT EXISTS (
        SELECT 1 FROM customer_identities
        WHERE customer_id = NEW.customer_id
    )
    BEGIN
        SELECT RAISE(ABORT, 'phone contact point owner does not exist');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_phone_contact_point_customer_id_update
    BEFORE UPDATE OF customer_id ON phone_contact_points
    WHEN NEW.customer_id <> OLD.customer_id
    BEGIN
        SELECT RAISE(ABORT, 'phone contact point customer_id is immutable');
    END
    """,
)


def _migration_1_create_phone_contact_points(connection: sqlite3.Connection) -> None:
    connection.execute(_CREATE_PHONE_CONTACT_POINTS)
    for statement in _PHONE_INDEXES:
        connection.execute(statement)
    for statement in _IMMUTABLE_OWNER_TRIGGERS:
        connection.execute(statement)


_MIGRATIONS = (
    (1, "create_phone_contact_points", _migration_1_create_phone_contact_points),
)


class SQLitePhoneContactPointRepository:
    def __init__(self, db_path: str | Path) -> None:
        self._conn = sqlite3.connect(str(db_path))
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._manage_transactions = True
        try:
            apply_migrations(self._conn, "phone_contact_points", _MIGRATIONS)
        except Exception:
            self._conn.close()
            raise

    @classmethod
    def from_connection(
        cls, connection: sqlite3.Connection
    ) -> SQLitePhoneContactPointRepository:
        repo = cls.__new__(cls)
        repo._conn = connection
        repo._conn.execute("PRAGMA foreign_keys = ON")
        repo._manage_transactions = False
        apply_migrations(connection, "phone_contact_points", _MIGRATIONS)
        return repo

    def _write_scope(self):  # noqa: ANN202
        return self._conn if self._manage_transactions else nullcontext()

    def close(self) -> None:
        self._conn.close()

    def add(self, point: PhoneContactPoint) -> None:
        validate_phone_contact_point(point)
        with self._write_scope():
            self._conn.execute(
                "INSERT INTO phone_contact_points VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                self._values(point),
            )

    def get_by_id(self, phone_contact_point_id: str) -> PhoneContactPoint | None:
        row = self._conn.execute(
            "SELECT * FROM phone_contact_points WHERE phone_contact_point_id = ?",
            (phone_contact_point_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_point(row)

    def list_by_customer_id(self, customer_id: str) -> list[PhoneContactPoint]:
        rows = self._conn.execute(
            """
            SELECT * FROM phone_contact_points
            WHERE customer_id = ?
            ORDER BY created_at, phone_contact_point_id
            """,
            (customer_id,),
        ).fetchall()
        return [self._row_to_point(row) for row in rows]

    def find_active_by_normalized_phone(
        self, normalized_phone: str
    ) -> list[PhoneContactPoint]:
        canonical = normalize_phone_for_contact_point(normalized_phone)
        rows = self._conn.execute(
            """
            SELECT p.*
            FROM phone_contact_points p
            JOIN customer_identities c ON c.customer_id = p.customer_id
            WHERE p.normalized_phone = ?
              AND p.status = ?
              AND c.status = ?
            ORDER BY p.created_at, p.phone_contact_point_id
            """,
            (
                canonical,
                ACTIVE_PHONE_CONTACT_POINT_STATUS,
                ACTIVE_CUSTOMER_IDENTITY_STATUS,
            ),
        ).fetchall()
        return [self._row_to_point(row) for row in rows]

    def _values(self, point: PhoneContactPoint) -> tuple:
        return (
            point.phone_contact_point_id,
            point.customer_id,
            point.normalized_phone,
            point.display_phone,
            point.status,
            point.created_at.isoformat(),
            point.updated_at.isoformat(),
            point.valid_from.isoformat() if point.valid_from else None,
            point.valid_to.isoformat() if point.valid_to else None,
        )

    def _row_to_point(self, row: tuple) -> PhoneContactPoint:
        return PhoneContactPoint(
            phone_contact_point_id=row[0],
            customer_id=row[1],
            normalized_phone=row[2],
            display_phone=row[3],
            status=validate_phone_contact_point_status(row[4]),
            created_at=datetime.fromisoformat(row[5]),
            updated_at=datetime.fromisoformat(row[6]),
            valid_from=datetime.fromisoformat(row[7]) if row[7] else None,
            valid_to=datetime.fromisoformat(row[8]) if row[8] else None,
        )
