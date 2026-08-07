"""SQLite persistence for immutable OrderDeliverySnapshot rows."""

from __future__ import annotations

import sqlite3
from contextlib import nullcontext
from pathlib import Path

from catering_system.domain.inquiry import validate_fulfillment_mode
from catering_system.domain.order_delivery_snapshot import OrderDeliverySnapshot
from catering_system.repositories.sqlite_migrations import apply_migrations


def _migration_1_create_tables(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE order_delivery_snapshots (
            snapshot_id TEXT PRIMARY KEY,
            order_id TEXT NOT NULL,
            order_version_id TEXT NOT NULL,
            fulfillment_mode TEXT NOT NULL,
            delivery_address TEXT,
            delivery_contact TEXT,
            time_window_text TEXT NOT NULL,
            location_text TEXT NOT NULL,
            created_from TEXT NOT NULL,
            UNIQUE (order_id, order_version_id)
        );
        CREATE INDEX idx_order_delivery_snapshots_order_id
            ON order_delivery_snapshots (order_id);
        """
    )
    connection.executescript(
        """
        CREATE TRIGGER trg_order_delivery_snapshot_owner_insert
        BEFORE INSERT ON order_delivery_snapshots
        WHEN NOT EXISTS (
            SELECT 1 FROM orders o
            JOIN order_versions v ON v.order_version_id = NEW.order_version_id
            WHERE o.order_id = NEW.order_id
              AND v.order_id = NEW.order_id
        )
        BEGIN
            SELECT RAISE(ABORT, 'order delivery snapshot owner is invalid');
        END;
        CREATE TRIGGER trg_order_delivery_snapshot_immutable_update
        BEFORE UPDATE ON order_delivery_snapshots
        BEGIN
            SELECT RAISE(ABORT, 'order delivery snapshot is immutable');
        END;
        CREATE TRIGGER trg_order_delivery_snapshot_immutable_delete
        BEFORE DELETE ON order_delivery_snapshots
        BEGIN
            SELECT RAISE(ABORT, 'order delivery snapshot is immutable');
        END;
        """
    )


_MIGRATIONS = ((1, "create_order_delivery_snapshots", _migration_1_create_tables),)


def _row_to_snapshot(row: tuple) -> OrderDeliverySnapshot:
    return OrderDeliverySnapshot(
        snapshot_id=row[0],
        order_id=row[1],
        order_version_id=row[2],
        fulfillment_mode=validate_fulfillment_mode(row[3]),
        delivery_address=row[4],
        delivery_contact=row[5],
        time_window_text=row[6],
        location_text=row[7],
        created_from=row[8],
    )


class SQLiteOrderDeliverySnapshotRepository:
    def __init__(self, db_path: str | Path) -> None:
        self._conn = sqlite3.connect(str(db_path))
        self._manage_transactions = True
        try:
            apply_migrations(self._conn, "order_delivery_snapshots", _MIGRATIONS)
        except Exception:
            self._conn.close()
            raise

    @classmethod
    def from_connection(
        cls, connection: sqlite3.Connection
    ) -> SQLiteOrderDeliverySnapshotRepository:
        repo = cls.__new__(cls)
        repo._conn = connection
        repo._manage_transactions = False
        apply_migrations(connection, "order_delivery_snapshots", _MIGRATIONS)
        return repo

    def _write_scope(self):  # noqa: ANN202
        return self._conn if self._manage_transactions else nullcontext()

    def close(self) -> None:
        self._conn.close()

    def get_by_order_version_id(
        self,
        order_id: str,
        order_version_id: str,
    ) -> OrderDeliverySnapshot | None:
        row = self._conn.execute(
            """
            SELECT snapshot_id, order_id, order_version_id, fulfillment_mode,
                   delivery_address, delivery_contact, time_window_text,
                   location_text, created_from
            FROM order_delivery_snapshots
            WHERE order_id = ? AND order_version_id = ?
            """,
            (order_id, order_version_id),
        ).fetchone()
        if row is None:
            return None
        return _row_to_snapshot(row)

    def create(self, snapshot: OrderDeliverySnapshot) -> None:
        with self._write_scope():
            self._conn.execute(
                """
                INSERT INTO order_delivery_snapshots (
                    snapshot_id, order_id, order_version_id, fulfillment_mode,
                    delivery_address, delivery_contact, time_window_text,
                    location_text, created_from
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.snapshot_id,
                    snapshot.order_id,
                    snapshot.order_version_id,
                    snapshot.fulfillment_mode,
                    snapshot.delivery_address,
                    snapshot.delivery_contact,
                    snapshot.time_window_text,
                    snapshot.location_text,
                    snapshot.created_from,
                ),
            )
