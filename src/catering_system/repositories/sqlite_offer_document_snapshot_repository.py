"""SQLite persistence for frozen customer offer document snapshots.

The owner trigger validates all three provenance ids against one
``offer_variants`` row, which denormalizes offer_id + offer_version_id +
variant_id together — so a single EXISTS proves the whole chain.
"""

from __future__ import annotations

import sqlite3
from contextlib import nullcontext
from pathlib import Path

from catering_system.domain.offer_document_snapshot import OfferDocumentSnapshot
from catering_system.repositories.offer_document_snapshot_repository import (
    OfferDocumentSnapshotRepository,
)
from catering_system.repositories.sqlite_migrations import apply_migrations
from catering_system.services.offer_document_snapshot_serialization import (
    snapshot_from_verified_row,
    snapshot_to_canonical_json,
)


def _migration_1_create_table(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE offer_document_snapshots (
            offer_document_snapshot_id TEXT PRIMARY KEY,
            offer_id TEXT NOT NULL,
            offer_version_id TEXT NOT NULL,
            offer_variant_id TEXT NOT NULL,
            document_reference TEXT NOT NULL,
            schema_version INTEGER NOT NULL,
            canonical_snapshot_json TEXT NOT NULL,
            document_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            created_by TEXT NOT NULL,
            UNIQUE (offer_version_id)
        );
        CREATE INDEX idx_offer_document_snapshots_offer_id
            ON offer_document_snapshots (offer_id);
        CREATE INDEX idx_offer_document_snapshots_offer_version_id
            ON offer_document_snapshots (offer_version_id);
        CREATE INDEX idx_offer_document_snapshots_document_reference
            ON offer_document_snapshots (document_reference);
        """
    )
    connection.executescript(
        """
        CREATE TRIGGER trg_offer_document_snapshot_owner_insert
        BEFORE INSERT ON offer_document_snapshots
        WHEN NOT EXISTS (
            SELECT 1 FROM offer_variants ov
            WHERE ov.offer_id = NEW.offer_id
              AND ov.offer_version_id = NEW.offer_version_id
              AND ov.variant_id = NEW.offer_variant_id
        )
        BEGIN
            SELECT RAISE(ABORT, 'offer document snapshot owner is invalid');
        END;
        CREATE TRIGGER trg_offer_document_snapshot_immutable_update
        BEFORE UPDATE ON offer_document_snapshots
        BEGIN
            SELECT RAISE(ABORT, 'offer document snapshot is immutable');
        END;
        CREATE TRIGGER trg_offer_document_snapshot_immutable_delete
        BEFORE DELETE ON offer_document_snapshots
        BEGIN
            SELECT RAISE(ABORT, 'offer document snapshot is immutable');
        END;
        """
    )


_MIGRATIONS = ((1, "create_offer_document_snapshots", _migration_1_create_table),)


class SQLiteOfferDocumentSnapshotRepository(OfferDocumentSnapshotRepository):
    def __init__(self, db_path: str | Path) -> None:
        self._conn = sqlite3.connect(str(db_path))
        self._manage_transactions = True
        try:
            apply_migrations(self._conn, "offer_document_snapshots", _MIGRATIONS)
        except Exception:
            self._conn.close()
            raise

    @classmethod
    def from_connection(
        cls, connection: sqlite3.Connection
    ) -> SQLiteOfferDocumentSnapshotRepository:
        repo = cls.__new__(cls)
        repo._conn = connection
        repo._manage_transactions = False
        apply_migrations(connection, "offer_document_snapshots", _MIGRATIONS)
        return repo

    def _write_scope(self):  # noqa: ANN202
        return self._conn if self._manage_transactions else nullcontext()

    def close(self) -> None:
        self._conn.close()

    def get_by_id(
        self, offer_document_snapshot_id: str
    ) -> OfferDocumentSnapshot | None:
        row = self._conn.execute(
            "SELECT canonical_snapshot_json, document_hash FROM "
            "offer_document_snapshots WHERE offer_document_snapshot_id = ?",
            (offer_document_snapshot_id,),
        ).fetchone()
        if row is None:
            return None
        return snapshot_from_verified_row(row[0], row[1])

    def get_by_offer_version_id(
        self, offer_version_id: str
    ) -> OfferDocumentSnapshot | None:
        row = self._conn.execute(
            "SELECT canonical_snapshot_json, document_hash FROM "
            "offer_document_snapshots WHERE offer_version_id = ?",
            (offer_version_id,),
        ).fetchone()
        if row is None:
            return None
        return snapshot_from_verified_row(row[0], row[1])

    def find_by_document_reference(
        self, document_reference: str
    ) -> OfferDocumentSnapshot | None:
        row = self._conn.execute(
            "SELECT canonical_snapshot_json, document_hash FROM "
            "offer_document_snapshots WHERE document_reference = ?",
            (document_reference,),
        ).fetchone()
        if row is None:
            return None
        return snapshot_from_verified_row(row[0], row[1])

    def insert(self, snapshot: OfferDocumentSnapshot) -> None:
        canonical = snapshot_to_canonical_json(snapshot)
        with self._write_scope():
            self._conn.execute(
                """
                INSERT INTO offer_document_snapshots (
                    offer_document_snapshot_id,
                    offer_id,
                    offer_version_id,
                    offer_variant_id,
                    document_reference,
                    schema_version,
                    canonical_snapshot_json,
                    document_hash,
                    created_at,
                    created_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.offer_document_snapshot_id,
                    snapshot.offer_id,
                    snapshot.offer_version_id,
                    snapshot.offer_variant_id,
                    snapshot.document_reference,
                    snapshot.schema_version,
                    canonical,
                    snapshot.document_hash,
                    snapshot.created_at.isoformat(),
                    snapshot.created_by,
                ),
            )
