"""SQLite persistence for Configurator one-time handoff records."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from catering_system.domain.configurator_handoff import (
    ConfiguratorHandoffOperation,
    ConfiguratorHandoffRecord,
)
from catering_system.repositories.sqlite_migrations import apply_migrations

_CREATE_CONFIGURATOR_HANDOFFS = """
CREATE TABLE IF NOT EXISTS configurator_handoffs (
    id TEXT PRIMARY KEY,
    token_hash TEXT NOT NULL,
    operation TEXT NOT NULL,
    inquiry_id TEXT NOT NULL,
    issued_for_account_id TEXT NOT NULL,
    issued_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    consumed_at TEXT,
    consumed_by_account_id TEXT
);
"""

_HANDOFF_INDEXES = (
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_configurator_handoffs_token_hash
    ON configurator_handoffs (token_hash);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_configurator_handoffs_inquiry
    ON configurator_handoffs (inquiry_id, operation);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_configurator_handoffs_expiry
    ON configurator_handoffs (expires_at, consumed_at);
    """,
)


def _migration_1_create_configurator_handoffs(connection: sqlite3.Connection) -> None:
    connection.execute(_CREATE_CONFIGURATOR_HANDOFFS)
    for statement in _HANDOFF_INDEXES:
        connection.execute(statement)


_MIGRATIONS = (
    (1, "create_configurator_handoffs", _migration_1_create_configurator_handoffs),
)


def _validate_operation(value: str) -> ConfiguratorHandoffOperation:
    if value != "prepare_first_offer":
        raise ValueError(f"unknown configurator handoff operation {value!r}")
    return "prepare_first_offer"


def _apply_migrations_in_current_transaction(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            component TEXT NOT NULL,
            version INTEGER NOT NULL,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL,
            PRIMARY KEY (component, version)
        )
        """
    )
    existing = {
        row[0]: row[1]
        for row in connection.execute(
            "SELECT version, name FROM schema_migrations WHERE component = ?",
            ("configurator_handoff",),
        ).fetchall()
    }
    for version, name, apply in _MIGRATIONS:
        if version in existing:
            if existing[version] != name:
                raise RuntimeError(
                    "configurator_handoff migration "
                    f"{version} name mismatch: database={existing[version]!r}, code={name!r}"
                )
            continue
        apply(connection)
        connection.execute(
            "INSERT INTO schema_migrations (component, version, name, applied_at) "
            "VALUES (?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))",
            ("configurator_handoff", version, name),
        )


class SQLiteConfiguratorHandoffRepository:
    @classmethod
    def from_connection(
        cls, connection: sqlite3.Connection
    ) -> SQLiteConfiguratorHandoffRepository:
        repo = cls.__new__(cls)
        repo._conn = connection
        repo._manage_transactions = False
        if connection.in_transaction:
            _apply_migrations_in_current_transaction(connection)
        else:
            apply_migrations(connection, "configurator_handoff", _MIGRATIONS)
        return repo

    def __init__(self, db_path: str | Path) -> None:
        self._conn = sqlite3.connect(str(db_path))
        self._manage_transactions = True
        try:
            apply_migrations(self._conn, "configurator_handoff", _MIGRATIONS)
        except Exception:
            self._conn.close()
            raise

    def close(self) -> None:
        self._conn.close()

    def add(self, record: ConfiguratorHandoffRecord) -> None:
        was_in_transaction = self._conn.in_transaction
        self._conn.execute(
            """
            INSERT INTO configurator_handoffs (
                id,
                token_hash,
                operation,
                inquiry_id,
                issued_for_account_id,
                issued_at,
                expires_at,
                consumed_at,
                consumed_by_account_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.id,
                record.token_hash,
                record.operation,
                record.inquiry_id,
                record.issued_for_account_id,
                record.issued_at.isoformat(),
                record.expires_at.isoformat(),
                record.consumed_at.isoformat()
                if record.consumed_at is not None
                else None,
                record.consumed_by_account_id,
            ),
        )
        if self._manage_transactions:
            self._conn.commit()
        elif self._conn.isolation_level is not None and not was_in_transaction:
            self._conn.commit()

    def get_by_token_hash(self, token_hash: str) -> ConfiguratorHandoffRecord | None:
        row = self._conn.execute(
            "SELECT * FROM configurator_handoffs WHERE token_hash = ?",
            (token_hash,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def consume(
        self,
        *,
        handoff_id: str,
        consumed_at: datetime,
        consumed_by_account_id: str,
    ) -> bool:
        was_in_transaction = self._conn.in_transaction
        updated = self._conn.execute(
            """
            UPDATE configurator_handoffs
            SET consumed_at = ?, consumed_by_account_id = ?
            WHERE id = ? AND consumed_at IS NULL
            """,
            (consumed_at.isoformat(), consumed_by_account_id, handoff_id),
        ).rowcount
        if self._manage_transactions:
            self._conn.commit()
        elif self._conn.isolation_level is not None and not was_in_transaction:
            self._conn.commit()
        return updated == 1

    def _row_to_record(
        self, row: sqlite3.Row | tuple[object, ...]
    ) -> ConfiguratorHandoffRecord:
        return ConfiguratorHandoffRecord(
            id=str(row[0]),
            token_hash=str(row[1]),
            operation=_validate_operation(str(row[2])),
            inquiry_id=str(row[3]),
            issued_for_account_id=str(row[4]),
            issued_at=datetime.fromisoformat(str(row[5])),
            expires_at=datetime.fromisoformat(str(row[6])),
            consumed_at=datetime.fromisoformat(str(row[7])) if row[7] else None,
            consumed_by_account_id=str(row[8]) if row[8] is not None else None,
        )
