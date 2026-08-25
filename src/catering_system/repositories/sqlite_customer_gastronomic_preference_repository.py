"""SQLite repository for explicit customer gastronomic preferences."""

from __future__ import annotations

import sqlite3
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path

from catering_system.domain.customer_gastronomic_preference import (
    CustomerGastronomicPreference,
    validate_customer_gastronomic_preference,
    validate_preference_kind,
    validate_preference_source,
)
from catering_system.repositories.sqlite_migrations import apply_migrations

_CREATE_PREFERENCES = """
CREATE TABLE IF NOT EXISTS customer_gastronomic_preferences (
    preference_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    value TEXT NOT NULL,
    source TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

_CUSTOMER_INDEX = """
CREATE INDEX IF NOT EXISTS idx_customer_gastronomic_preferences_customer
    ON customer_gastronomic_preferences (customer_id, updated_at);
"""

_CUSTOMER_KIND_INDEX = """
CREATE INDEX IF NOT EXISTS idx_customer_gastronomic_preferences_customer_kind
    ON customer_gastronomic_preferences (customer_id, kind);
"""


def _migration_1_create_preferences(connection: sqlite3.Connection) -> None:
    connection.execute(_CREATE_PREFERENCES)
    connection.execute(_CUSTOMER_INDEX)
    connection.execute(_CUSTOMER_KIND_INDEX)


_MIGRATIONS = (
    (1, "create_customer_gastronomic_preferences", _migration_1_create_preferences),
)


class SQLiteCustomerGastronomicPreferenceRepository:
    def __init__(self, db_path: str | Path) -> None:
        self._conn = sqlite3.connect(str(db_path))
        self._manage_transactions = True
        try:
            apply_migrations(
                self._conn,
                "customer_gastronomic_preferences",
                _MIGRATIONS,
            )
        except Exception:
            self._conn.close()
            raise

    @classmethod
    def from_connection(
        cls,
        connection: sqlite3.Connection,
    ) -> SQLiteCustomerGastronomicPreferenceRepository:
        repo = cls.__new__(cls)
        repo._conn = connection
        repo._manage_transactions = False
        apply_migrations(
            connection,
            "customer_gastronomic_preferences",
            _MIGRATIONS,
        )
        return repo

    def _write_scope(self):  # noqa: ANN202
        return self._conn if self._manage_transactions else nullcontext()

    def close(self) -> None:
        self._conn.close()

    def add(self, preference: CustomerGastronomicPreference) -> None:
        validate_customer_gastronomic_preference(preference)
        try:
            with self._write_scope():
                self._conn.execute(
                    """
                    INSERT INTO customer_gastronomic_preferences (
                        preference_id,
                        customer_id,
                        kind,
                        value,
                        source,
                        created_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    self._values(preference),
                )
        except sqlite3.IntegrityError as exc:
            raise KeyError(preference.preference_id) from exc

    def get_by_id(self, preference_id: str) -> CustomerGastronomicPreference | None:
        row = self._conn.execute(
            """
            SELECT preference_id, customer_id, kind, value, source, created_at, updated_at
            FROM customer_gastronomic_preferences
            WHERE preference_id = ?
            """,
            (preference_id,),
        ).fetchone()
        return None if row is None else self._row_to_preference(row)

    def list_by_customer(self, customer_id: str) -> list[CustomerGastronomicPreference]:
        rows = self._conn.execute(
            """
            SELECT preference_id, customer_id, kind, value, source, created_at, updated_at
            FROM customer_gastronomic_preferences
            WHERE customer_id = ?
            ORDER BY updated_at DESC, preference_id DESC
            """,
            (customer_id,),
        ).fetchall()
        return [self._row_to_preference(row) for row in rows]

    def update(self, preference: CustomerGastronomicPreference) -> None:
        validate_customer_gastronomic_preference(preference)
        with self._write_scope():
            updated = self._conn.execute(
                """
                UPDATE customer_gastronomic_preferences
                SET customer_id = ?, kind = ?, value = ?, source = ?, updated_at = ?
                WHERE preference_id = ?
                """,
                (
                    preference.customer_id,
                    preference.kind,
                    preference.value,
                    preference.source,
                    preference.updated_at.isoformat(),
                    preference.preference_id,
                ),
            ).rowcount
            if updated != 1:
                raise KeyError(preference.preference_id)

    def delete(self, preference_id: str) -> None:
        with self._write_scope():
            deleted = self._conn.execute(
                "DELETE FROM customer_gastronomic_preferences WHERE preference_id = ?",
                (preference_id,),
            ).rowcount
            if deleted != 1:
                raise KeyError(preference_id)

    @staticmethod
    def _values(preference: CustomerGastronomicPreference) -> tuple[str, ...]:
        return (
            preference.preference_id,
            preference.customer_id,
            preference.kind,
            preference.value,
            preference.source,
            preference.created_at.isoformat(),
            preference.updated_at.isoformat(),
        )

    @staticmethod
    def _row_to_preference(row: tuple[str, ...]) -> CustomerGastronomicPreference:
        return CustomerGastronomicPreference(
            preference_id=row[0],
            customer_id=row[1],
            kind=validate_preference_kind(row[2]),
            value=row[3],
            source=validate_preference_source(row[4]),
            created_at=datetime.fromisoformat(row[5]),
            updated_at=datetime.fromisoformat(row[6]),
        )
