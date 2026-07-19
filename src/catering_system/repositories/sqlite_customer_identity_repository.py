"""SQLite CustomerIdentity repository."""

from __future__ import annotations

import sqlite3
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path
from catering_system.domain.customer_identity import (
    CustomerIdentity,
    validate_customer_identity,
    validate_customer_identity_status,
)
from catering_system.repositories.sqlite_migrations import apply_migrations

_CREATE_CUSTOMER_IDENTITIES = """
CREATE TABLE IF NOT EXISTS customer_identities (
    customer_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    company_name TEXT,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

_CUSTOMER_STATUS_INDEX = """
CREATE INDEX IF NOT EXISTS idx_customer_identities_status
    ON customer_identities (status);
"""


def _migration_1_create_customer_identities(connection: sqlite3.Connection) -> None:
    connection.execute(_CREATE_CUSTOMER_IDENTITIES)
    connection.execute(_CUSTOMER_STATUS_INDEX)


_MIGRATIONS = (
    (1, "create_customer_identities", _migration_1_create_customer_identities),
)


class SQLiteCustomerIdentityRepository:
    def __init__(self, db_path: str | Path) -> None:
        self._conn = sqlite3.connect(str(db_path))
        self._manage_transactions = True
        try:
            apply_migrations(self._conn, "customer_identities", _MIGRATIONS)
        except Exception:
            self._conn.close()
            raise

    @classmethod
    def from_connection(
        cls, connection: sqlite3.Connection
    ) -> SQLiteCustomerIdentityRepository:
        repo = cls.__new__(cls)
        repo._conn = connection
        repo._manage_transactions = False
        apply_migrations(connection, "customer_identities", _MIGRATIONS)
        return repo

    def _write_scope(self):  # noqa: ANN202
        return self._conn if self._manage_transactions else nullcontext()

    def close(self) -> None:
        self._conn.close()

    def add(self, identity: CustomerIdentity) -> None:
        validate_customer_identity(identity)
        with self._write_scope():
            self._conn.execute(
                "INSERT INTO customer_identities VALUES (?, ?, ?, ?, ?, ?)",
                self._values(identity),
            )

    def get_by_id(self, customer_id: str) -> CustomerIdentity | None:
        row = self._conn.execute(
            "SELECT * FROM customer_identities WHERE customer_id = ?",
            (customer_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_identity(row)

    def update(self, identity: CustomerIdentity) -> None:
        validate_customer_identity(identity)
        with self._write_scope():
            updated = self._conn.execute(
                """
                UPDATE customer_identities
                SET display_name = ?, company_name = ?, status = ?, updated_at = ?
                WHERE customer_id = ?
                """,
                (
                    identity.display_name,
                    identity.company_name,
                    identity.status,
                    identity.updated_at.isoformat(),
                    identity.customer_id,
                ),
            ).rowcount
            if updated != 1:
                raise KeyError(identity.customer_id)

    def _values(self, identity: CustomerIdentity) -> tuple:
        return (
            identity.customer_id,
            identity.display_name,
            identity.company_name,
            identity.status,
            identity.created_at.isoformat(),
            identity.updated_at.isoformat(),
        )

    def _row_to_identity(self, row: tuple) -> CustomerIdentity:
        return CustomerIdentity(
            customer_id=row[0],
            display_name=row[1],
            company_name=row[2],
            status=validate_customer_identity_status(row[3]),
            created_at=datetime.fromisoformat(row[4]),
            updated_at=datetime.fromisoformat(row[5]),
        )
