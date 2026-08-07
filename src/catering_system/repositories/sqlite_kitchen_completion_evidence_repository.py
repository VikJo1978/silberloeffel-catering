"""SQLite persistence for append-only kitchen completion evidence."""

from __future__ import annotations

import sqlite3
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path

from catering_system.domain.kitchen_completion_evidence import KitchenCompletionEvidence
from catering_system.repositories.sqlite_migrations import apply_migrations


def _migration_1_create_tables(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE kitchen_completion_evidence (
            kitchen_completion_evidence_id TEXT PRIMARY KEY,
            order_id TEXT NOT NULL,
            order_version_id TEXT NOT NULL,
            completed_at TEXT NOT NULL,
            recorded_at TEXT NOT NULL,
            recorded_by TEXT NOT NULL,
            evidence_reference TEXT NOT NULL,
            UNIQUE (order_id, order_version_id)
        );
        CREATE INDEX idx_kitchen_completion_evidence_order_id
            ON kitchen_completion_evidence (order_id);
        """
    )
    connection.executescript(
        """
        CREATE TRIGGER trg_kitchen_completion_evidence_owner_insert
        BEFORE INSERT ON kitchen_completion_evidence
        WHEN NOT EXISTS (
            SELECT 1 FROM orders o
            JOIN order_versions v ON v.order_version_id = NEW.order_version_id
            WHERE o.order_id = NEW.order_id
              AND v.order_id = NEW.order_id
              AND o.effective_order_version_id = NEW.order_version_id
        )
        BEGIN
            SELECT RAISE(ABORT, 'kitchen completion owner is invalid');
        END;
        CREATE TRIGGER trg_kitchen_completion_evidence_immutable_update
        BEFORE UPDATE ON kitchen_completion_evidence
        BEGIN
            SELECT RAISE(ABORT, 'kitchen completion evidence is immutable');
        END;
        CREATE TRIGGER trg_kitchen_completion_evidence_immutable_delete
        BEFORE DELETE ON kitchen_completion_evidence
        BEGIN
            SELECT RAISE(ABORT, 'kitchen completion evidence is immutable');
        END;
        """
    )


_MIGRATIONS = (
    (1, "create_kitchen_completion_evidence", _migration_1_create_tables),
)


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _row_to_evidence(row: tuple) -> KitchenCompletionEvidence:
    return KitchenCompletionEvidence(
        kitchen_completion_evidence_id=row[0],
        order_id=row[1],
        order_version_id=row[2],
        completed_at=_parse_datetime(row[3]),
        recorded_at=_parse_datetime(row[4]),
        recorded_by=row[5],
        evidence_reference=row[6],
    )


class SQLiteKitchenCompletionEvidenceRepository:
    def __init__(self, db_path: str | Path) -> None:
        self._conn = sqlite3.connect(str(db_path))
        self._manage_transactions = True
        try:
            apply_migrations(
                self._conn,
                "kitchen_completion_evidence",
                _MIGRATIONS,
            )
        except Exception:
            self._conn.close()
            raise

    @classmethod
    def from_connection(
        cls, connection: sqlite3.Connection
    ) -> SQLiteKitchenCompletionEvidenceRepository:
        repo = cls.__new__(cls)
        repo._conn = connection
        repo._manage_transactions = False
        apply_migrations(connection, "kitchen_completion_evidence", _MIGRATIONS)
        return repo

    def _write_scope(self):  # noqa: ANN202
        return self._conn if self._manage_transactions else nullcontext()

    def close(self) -> None:
        self._conn.close()

    def get_by_order_version_id(
        self,
        order_id: str,
        order_version_id: str,
    ) -> KitchenCompletionEvidence | None:
        row = self._conn.execute(
            """
            SELECT kitchen_completion_evidence_id, order_id, order_version_id,
                   completed_at, recorded_at, recorded_by, evidence_reference
            FROM kitchen_completion_evidence
            WHERE order_id = ? AND order_version_id = ?
            """,
            (order_id, order_version_id),
        ).fetchone()
        if row is None:
            return None
        return _row_to_evidence(row)

    def append(self, evidence: KitchenCompletionEvidence) -> None:
        existing = self.get_by_order_version_id(
            evidence.order_id,
            evidence.order_version_id,
        )
        if existing is not None:
            if existing != evidence:
                raise ValueError("kitchen completion evidence conflict")
            return
        with self._write_scope():
            self._conn.execute(
                """
                INSERT INTO kitchen_completion_evidence (
                    kitchen_completion_evidence_id,
                    order_id,
                    order_version_id,
                    completed_at,
                    recorded_at,
                    recorded_by,
                    evidence_reference
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evidence.kitchen_completion_evidence_id,
                    evidence.order_id,
                    evidence.order_version_id,
                    evidence.completed_at.isoformat(),
                    evidence.recorded_at.isoformat(),
                    evidence.recorded_by,
                    evidence.evidence_reference,
                ),
            )
