"""SQLite persistence for frozen order confirmation document snapshots."""

from __future__ import annotations

import sqlite3
from contextlib import nullcontext
from pathlib import Path

from catering_system.domain.order_confirmation_document import (
    OrderConfirmationDocumentSnapshot,
    SCHEMA_VERSION,
)
from catering_system.repositories.order_confirmation_document_repository import (
    OrderConfirmationDocumentRepository,
)
from catering_system.repositories.sqlite_migrations import apply_migrations
from catering_system.services.order_confirmation_document_serialization import (
    snapshot_from_canonical_json,
    snapshot_to_canonical_json,
)


def _migration_1_create_table(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE order_confirmation_document_snapshots (
            document_snapshot_id TEXT PRIMARY KEY,
            order_id TEXT NOT NULL,
            order_version_id TEXT NOT NULL,
            offer_version_id TEXT NOT NULL,
            schema_version INTEGER NOT NULL,
            canonical_snapshot_json TEXT NOT NULL,
            document_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            created_by TEXT NOT NULL,
            UNIQUE (order_version_id)
        );
        CREATE INDEX idx_order_confirmation_documents_order_id
            ON order_confirmation_document_snapshots (order_id);
        CREATE INDEX idx_order_confirmation_documents_order_version_id
            ON order_confirmation_document_snapshots (order_version_id);
        """
    )
    connection.executescript(
        """
        CREATE TRIGGER trg_order_confirmation_document_owner_insert
        BEFORE INSERT ON order_confirmation_document_snapshots
        WHEN NOT EXISTS (
            SELECT 1 FROM orders o
            JOIN order_versions v ON v.order_id = o.order_id
            WHERE o.order_id = NEW.order_id
              AND v.order_version_id = NEW.order_version_id
        )
        BEGIN
            SELECT RAISE(ABORT, 'confirmation document owner is invalid');
        END;
        CREATE TRIGGER trg_order_confirmation_document_immutable_update
        BEFORE UPDATE ON order_confirmation_document_snapshots
        BEGIN
            SELECT RAISE(ABORT, 'confirmation document snapshot is immutable');
        END;
        CREATE TRIGGER trg_order_confirmation_document_immutable_delete
        BEFORE DELETE ON order_confirmation_document_snapshots
        BEGIN
            SELECT RAISE(ABORT, 'confirmation document snapshot is immutable');
        END;
        """
    )


_MIGRATIONS = (
    (1, "create_order_confirmation_document_snapshots", _migration_1_create_table),
)


class SQLiteOrderConfirmationDocumentRepository(OrderConfirmationDocumentRepository):
    def __init__(self, db_path: str | Path) -> None:
        self._conn = sqlite3.connect(str(db_path))
        self._manage_transactions = True
        try:
            apply_migrations(self._conn, "order_confirmation_documents", _MIGRATIONS)
        except Exception:
            self._conn.close()
            raise

    @classmethod
    def from_connection(
        cls, connection: sqlite3.Connection
    ) -> SQLiteOrderConfirmationDocumentRepository:
        repo = cls.__new__(cls)
        repo._conn = connection
        repo._manage_transactions = False
        apply_migrations(connection, "order_confirmation_documents", _MIGRATIONS)
        return repo

    def _write_scope(self):  # noqa: ANN202
        return self._conn if self._manage_transactions else nullcontext()

    def close(self) -> None:
        self._conn.close()

    def get_by_id(
        self, document_snapshot_id: str
    ) -> OrderConfirmationDocumentSnapshot | None:
        row = self._conn.execute(
            "SELECT canonical_snapshot_json FROM order_confirmation_document_snapshots "
            "WHERE document_snapshot_id = ?",
            (document_snapshot_id,),
        ).fetchone()
        if row is None:
            return None
        return snapshot_from_canonical_json(row[0])

    def get_by_order_version_id(
        self, order_version_id: str
    ) -> OrderConfirmationDocumentSnapshot | None:
        row = self._conn.execute(
            "SELECT canonical_snapshot_json FROM order_confirmation_document_snapshots "
            "WHERE order_version_id = ?",
            (order_version_id,),
        ).fetchone()
        if row is None:
            return None
        return snapshot_from_canonical_json(row[0])

    def get_latest_for_order(
        self, order_id: str
    ) -> OrderConfirmationDocumentSnapshot | None:
        row = self._conn.execute(
            "SELECT canonical_snapshot_json FROM order_confirmation_document_snapshots "
            "WHERE order_id = ? ORDER BY created_at DESC LIMIT 1",
            (order_id,),
        ).fetchone()
        if row is None:
            return None
        return snapshot_from_canonical_json(row[0])

    def insert(self, snapshot: OrderConfirmationDocumentSnapshot) -> None:
        canonical = snapshot_to_canonical_json(snapshot)
        with self._write_scope():
            self._conn.execute(
                """
                INSERT INTO order_confirmation_document_snapshots (
                    document_snapshot_id,
                    order_id,
                    order_version_id,
                    offer_version_id,
                    schema_version,
                    canonical_snapshot_json,
                    document_hash,
                    created_at,
                    created_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.document_snapshot_id,
                    snapshot.order_id,
                    snapshot.order_version_id,
                    snapshot.offer_version_id,
                    snapshot.schema_version or SCHEMA_VERSION,
                    canonical,
                    snapshot.document_hash,
                    snapshot.created_at.isoformat(),
                    snapshot.created_by,
                ),
            )
