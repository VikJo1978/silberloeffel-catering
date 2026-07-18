"""SQLite order repository — same OrderRepository Protocol as the in-memory baseline.

Persistence adapter only: no business rules, no new truth axis. Schema mirrors
the frozen Order/OrderVersion field set (incl. the two OPERATIONAL_CORE §7 fields).
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import nullcontext
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

from catering_system.domain.inquiry import validate_planning_mode
from catering_system.domain.order import Order, OrderVersion
from catering_system.repositories.sqlite_migrations import apply_migrations

_CREATE_ORDERS = """
CREATE TABLE IF NOT EXISTS orders (
    order_id TEXT PRIMARY KEY,
    source_inquiry_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    candidate_order_version_id TEXT,
    effective_order_version_id TEXT,
    cancelled_at TEXT
)
"""

_CREATE_ORDER_VERSIONS = """
CREATE TABLE IF NOT EXISTS order_versions (
    order_version_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    version_number INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    event_date TEXT NOT NULL,
    time_window_text TEXT NOT NULL,
    location_text TEXT NOT NULL,
    guest_count_estimate INTEGER,
    planning_mode TEXT NOT NULL,
    kitchen_print_confirmed_at TEXT,
    parent_order_version_id TEXT,
    created_by TEXT,
    change_reason TEXT,
    changed_fields_json TEXT NOT NULL DEFAULT '[]'
)
"""

_UNIQUE_VERSION_NUMBER_INDEX = """
CREATE UNIQUE INDEX IF NOT EXISTS uq_order_versions_order_version_number
    ON order_versions (order_id, version_number);
"""

_INVARIANT_TRIGGERS = (
    """CREATE TRIGGER IF NOT EXISTS trg_order_version_owner_insert
    BEFORE INSERT ON order_versions
    WHEN NOT EXISTS (SELECT 1 FROM orders WHERE order_id = NEW.order_id)
    BEGIN SELECT RAISE(ABORT, 'order_version owner does not exist'); END""",
    """CREATE TRIGGER IF NOT EXISTS trg_order_version_owner_update
    BEFORE UPDATE OF order_id ON order_versions
    WHEN NOT EXISTS (SELECT 1 FROM orders WHERE order_id = NEW.order_id)
    BEGIN SELECT RAISE(ABORT, 'order_version owner does not exist'); END""",
    """CREATE TRIGGER IF NOT EXISTS trg_order_references_insert
    BEFORE INSERT ON orders
    WHEN (NEW.candidate_order_version_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM order_versions
            WHERE order_version_id = NEW.candidate_order_version_id
              AND order_id = NEW.order_id))
      OR (NEW.effective_order_version_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM order_versions
            WHERE order_version_id = NEW.effective_order_version_id
              AND order_id = NEW.order_id))
    BEGIN SELECT RAISE(ABORT, 'order version reference is not owned'); END""",
    """CREATE TRIGGER IF NOT EXISTS trg_order_references_update
    BEFORE UPDATE OF candidate_order_version_id, effective_order_version_id ON orders
    WHEN (NEW.candidate_order_version_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM order_versions
            WHERE order_version_id = NEW.candidate_order_version_id
              AND order_id = NEW.order_id))
      OR (NEW.effective_order_version_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM order_versions
            WHERE order_version_id = NEW.effective_order_version_id
              AND order_id = NEW.order_id))
    BEGIN SELECT RAISE(ABORT, 'order version reference is not owned'); END""",
)

_INVARIANT_MUTATION_TRIGGERS = (
    """CREATE TRIGGER IF NOT EXISTS trg_order_owner_delete
    BEFORE DELETE ON orders
    WHEN EXISTS (SELECT 1 FROM order_versions WHERE order_id = OLD.order_id)
    BEGIN SELECT RAISE(ABORT, 'order still owns versions'); END""",
    """CREATE TRIGGER IF NOT EXISTS trg_order_id_update
    BEFORE UPDATE OF order_id ON orders
    WHEN NEW.order_id <> OLD.order_id
      AND EXISTS (SELECT 1 FROM order_versions WHERE order_id = OLD.order_id)
    BEGIN SELECT RAISE(ABORT, 'order still owns versions'); END""",
    """CREATE TRIGGER IF NOT EXISTS trg_referenced_order_version_delete
    BEFORE DELETE ON order_versions
    WHEN EXISTS (
        SELECT 1 FROM orders
        WHERE candidate_order_version_id = OLD.order_version_id
           OR effective_order_version_id = OLD.order_version_id)
    BEGIN SELECT RAISE(ABORT, 'order version is referenced'); END""",
    """CREATE TRIGGER IF NOT EXISTS trg_referenced_order_version_update
    BEFORE UPDATE OF order_version_id, order_id ON order_versions
    WHEN EXISTS (
        SELECT 1 FROM orders
        WHERE (candidate_order_version_id = OLD.order_version_id
            OR effective_order_version_id = OLD.order_version_id)
          AND (NEW.order_version_id <> OLD.order_version_id
            OR NEW.order_id <> orders.order_id))
    BEGIN SELECT RAISE(ABORT, 'order version is referenced'); END""",
)


def _migration_1_create_tables(connection: sqlite3.Connection) -> None:
    connection.execute(_CREATE_ORDERS)
    connection.execute(_CREATE_ORDER_VERSIONS)
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_order_versions_order_id "
        "ON order_versions (order_id, version_number)"
    )


def _migration_2_add_cancelled_at(connection: sqlite3.Connection) -> None:
    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(orders)").fetchall()
    }
    if "cancelled_at" not in columns:
        connection.execute("ALTER TABLE orders ADD COLUMN cancelled_at TEXT")


def _migration_3_unique_version_numbers(connection: sqlite3.Connection) -> None:
    duplicate = connection.execute(
        "SELECT order_id, version_number FROM order_versions "
        "GROUP BY order_id, version_number HAVING COUNT(*) > 1 LIMIT 1"
    ).fetchone()
    if duplicate is not None:
        raise ValueError(
            "cannot enforce unique order version numbers: duplicate "
            f"version_number {duplicate[1]} for order {duplicate[0]!r}"
        )
    connection.execute(_UNIQUE_VERSION_NUMBER_INDEX)


def _migration_4_order_invariants(connection: sqlite3.Connection) -> None:
    orphan = connection.execute(
        "SELECT v.order_version_id FROM order_versions v "
        "LEFT JOIN orders o ON o.order_id = v.order_id "
        "WHERE o.order_id IS NULL LIMIT 1"
    ).fetchone()
    invalid_reference = connection.execute(
        "SELECT o.order_id FROM orders o "
        "LEFT JOIN order_versions c ON c.order_version_id = o.candidate_order_version_id "
        "LEFT JOIN order_versions e ON e.order_version_id = o.effective_order_version_id "
        "WHERE (o.candidate_order_version_id IS NOT NULL "
        "AND (c.order_version_id IS NULL OR c.order_id <> o.order_id)) "
        "OR (o.effective_order_version_id IS NOT NULL "
        "AND (e.order_version_id IS NULL OR e.order_id <> o.order_id)) LIMIT 1"
    ).fetchone()
    if orphan is not None:
        raise ValueError(f"orphan order version {orphan[0]!r}")
    if invalid_reference is not None:
        raise ValueError(f"invalid order version reference on {invalid_reference[0]!r}")
    for trigger in _INVARIANT_TRIGGERS:
        connection.execute(trigger)


def _migration_5_protect_invariant_mutations(
    connection: sqlite3.Connection,
) -> None:
    for trigger in _INVARIANT_MUTATION_TRIGGERS:
        connection.execute(trigger)


def _migration_6_unique_active_source_inquiry(
    connection: sqlite3.Connection,
) -> None:
    """PROXMOX_OFFICE_SERVER_CORE_API_PACK_V1 §6.2: at most one ACTIVE order
    per inquiry. Deliberately partial — re-conversion after Storno is
    existing, wanted behavior, so cancelled orders never conflict. Fails
    closed on pre-existing duplicates (precedent: inquiries migration 3)."""
    duplicate = connection.execute(
        "SELECT source_inquiry_id FROM orders WHERE cancelled_at IS NULL "
        "GROUP BY source_inquiry_id HAVING COUNT(*) > 1 LIMIT 1"
    ).fetchone()
    if duplicate is not None:
        raise ValueError(
            "cannot enforce one active order per inquiry: inquiry "
            f"{duplicate[0]!r} has more than one non-cancelled order; "
            "resolve manually before migrating"
        )
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_orders_active_source_inquiry "
        "ON orders (source_inquiry_id) WHERE cancelled_at IS NULL"
    )


def _migration_7_immutable_version_change_metadata(
    connection: sqlite3.Connection,
) -> None:
    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(order_versions)")
    }
    additions = (
        ("parent_order_version_id", "TEXT"),
        ("created_by", "TEXT"),
        ("change_reason", "TEXT"),
        ("changed_fields_json", "TEXT NOT NULL DEFAULT '[]'"),
    )
    for name, declaration in additions:
        if name not in columns:
            connection.execute(
                f"ALTER TABLE order_versions ADD COLUMN {name} {declaration}"
            )
    connection.execute(
        """CREATE TRIGGER IF NOT EXISTS trg_order_version_parent_insert
        BEFORE INSERT ON order_versions
        WHEN NEW.parent_order_version_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM order_versions parent
            WHERE parent.order_version_id = NEW.parent_order_version_id
              AND parent.order_id = NEW.order_id)
        BEGIN SELECT RAISE(ABORT, 'order version parent is not owned'); END"""
    )
    connection.execute(
        """CREATE TRIGGER IF NOT EXISTS trg_order_version_immutable_update
        BEFORE UPDATE ON order_versions
        WHEN NEW.order_version_id IS NOT OLD.order_version_id
          OR NEW.order_id IS NOT OLD.order_id
          OR NEW.version_number IS NOT OLD.version_number
          OR NEW.created_at IS NOT OLD.created_at
          OR NEW.event_date IS NOT OLD.event_date
          OR NEW.time_window_text IS NOT OLD.time_window_text
          OR NEW.location_text IS NOT OLD.location_text
          OR NEW.guest_count_estimate IS NOT OLD.guest_count_estimate
          OR NEW.planning_mode IS NOT OLD.planning_mode
          OR NEW.parent_order_version_id IS NOT OLD.parent_order_version_id
          OR NEW.created_by IS NOT OLD.created_by
          OR NEW.change_reason IS NOT OLD.change_reason
          OR NEW.changed_fields_json IS NOT OLD.changed_fields_json
          OR (OLD.kitchen_print_confirmed_at IS NOT NULL
              AND NEW.kitchen_print_confirmed_at IS NOT OLD.kitchen_print_confirmed_at)
        BEGIN SELECT RAISE(ABORT, 'order version snapshot is immutable'); END"""
    )
    connection.execute(
        """CREATE TRIGGER IF NOT EXISTS trg_order_version_history_no_delete
        BEFORE DELETE ON order_versions
        BEGIN SELECT RAISE(ABORT, 'order version history is append-only'); END"""
    )


_MIGRATIONS = (
    (1, "create_order_tables", _migration_1_create_tables),
    (2, "add_cancelled_at", _migration_2_add_cancelled_at),
    (3, "unique_version_numbers", _migration_3_unique_version_numbers),
    (4, "order_invariant_triggers", _migration_4_order_invariants),
    (5, "protect_invariant_mutations", _migration_5_protect_invariant_mutations),
    (6, "unique_active_source_inquiry", _migration_6_unique_active_source_inquiry),
    (
        7,
        "immutable_version_change_metadata",
        _migration_7_immutable_version_change_metadata,
    ),
)


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


class SQLiteOrderRepository:
    def __init__(self, db_path: str | Path) -> None:
        self._conn = sqlite3.connect(str(db_path))
        self._manage_transactions = True
        try:
            apply_migrations(self._conn, "orders", _MIGRATIONS)
        except Exception:
            self._conn.close()
            raise

    @classmethod
    def from_connection(cls, connection: sqlite3.Connection) -> SQLiteOrderRepository:
        """Externally-managed transaction mode (PROXMOX pack §6.1): the
        caller owns BEGIN/COMMIT/ROLLBACK on the shared connection; write
        methods here must not auto-commit. Migrations still apply."""
        repo = cls.__new__(cls)
        repo._conn = connection
        repo._manage_transactions = False
        apply_migrations(connection, "orders", _MIGRATIONS)
        return repo

    def _write_scope(self):  # noqa: ANN202
        # `with self._write_scope():` commits on exit — correct standalone, fatal
        # inside an externally-owned transaction (it would commit half a
        # command). nullcontext leaves control with the coordinator.
        return self._conn if self._manage_transactions else nullcontext()

    def close(self) -> None:
        self._conn.close()

    def save_order_with_initial_version(
        self, order: Order, version: OrderVersion
    ) -> None:
        """Create the aggregate root and v1 in one SQLite transaction."""
        if version.order_id != order.order_id or version.version_number != 1:
            raise ValueError("initial version must be v1 of the supplied order")
        with self._write_scope():
            self._conn.execute(
                "INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?)",
                self._order_values(order),
            )
            self._conn.execute(
                "INSERT INTO order_versions VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                self._version_values(version),
            )

    def get_order(self, order_id: str) -> Order | None:
        row = self._conn.execute(
            "SELECT * FROM orders WHERE order_id = ?", (order_id,)
        ).fetchone()
        if row is None:
            return None
        return Order(
            order_id=row[0],
            source_inquiry_id=row[1],
            created_at=_dt(row[2]),
            updated_at=_dt(row[3]),
            candidate_order_version_id=row[4],
            effective_order_version_id=row[5],
            cancelled_at=_dt(row[6]) if row[6] is not None else None,
        )

    def update_order(self, order: Order) -> None:
        with self._write_scope():
            updated = self._update_order_row(order)
            if updated != 1:
                raise KeyError(order.order_id)

    def list_orders(self) -> list[Order]:
        rows = self._conn.execute("SELECT * FROM orders ORDER BY order_id").fetchall()
        return [
            Order(
                order_id=r[0],
                source_inquiry_id=r[1],
                created_at=_dt(r[2]),
                updated_at=_dt(r[3]),
                candidate_order_version_id=r[4],
                effective_order_version_id=r[5],
                cancelled_at=_dt(r[6]) if r[6] is not None else None,
            )
            for r in rows
        ]

    def append_order_version(self, order: Order, version: OrderVersion) -> None:
        """Append a version and update its aggregate root in one transaction."""
        if version.order_id != order.order_id or version.version_number < 1:
            raise ValueError("version must belong to the supplied order")
        with self._write_scope():
            self._conn.execute(
                "INSERT INTO order_versions VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                self._version_values(version),
            )
            updated = self._update_order_row(order)
            if updated != 1:
                raise KeyError(order.order_id)

    def update_order_version(self, version: OrderVersion) -> None:
        existing = self.get_order_version(version.order_version_id)
        if existing is None:
            raise KeyError(version.order_version_id)
        if (
            replace(
                existing,
                kitchen_print_confirmed_at=version.kitchen_print_confirmed_at,
            )
            != version
        ):
            raise ValueError("order version snapshot is immutable")
        if (
            existing.kitchen_print_confirmed_at is not None
            and version.kitchen_print_confirmed_at
            != existing.kitchen_print_confirmed_at
        ):
            raise ValueError("kitchen print confirmation is immutable")
        with self._write_scope():
            updated = self._conn.execute(
                "UPDATE order_versions SET kitchen_print_confirmed_at = ? "
                "WHERE order_version_id = ?",
                (
                    version.kitchen_print_confirmed_at.isoformat()
                    if version.kitchen_print_confirmed_at is not None
                    else None,
                    version.order_version_id,
                ),
            ).rowcount
            if updated != 1:
                raise KeyError(version.order_version_id)

    def _update_order_row(self, order: Order) -> int:
        return self._conn.execute(
            """
            UPDATE orders SET
                source_inquiry_id = ?, created_at = ?, updated_at = ?,
                candidate_order_version_id = ?, effective_order_version_id = ?,
                cancelled_at = ?
            WHERE order_id = ?
            """,
            self._order_values(order)[1:] + (order.order_id,),
        ).rowcount

    @staticmethod
    def _order_values(order: Order) -> tuple:
        return (
            order.order_id,
            order.source_inquiry_id,
            order.created_at.isoformat(),
            order.updated_at.isoformat(),
            order.candidate_order_version_id,
            order.effective_order_version_id,
            order.cancelled_at.isoformat() if order.cancelled_at is not None else None,
        )

    @staticmethod
    def _version_values(version: OrderVersion) -> tuple:
        return (
            version.order_version_id,
            version.order_id,
            version.version_number,
            version.created_at.isoformat(),
            version.event_date.isoformat(),
            version.time_window_text,
            version.location_text,
            version.guest_count_estimate,
            version.planning_mode,
            version.kitchen_print_confirmed_at.isoformat()
            if version.kitchen_print_confirmed_at is not None
            else None,
            version.parent_order_version_id,
            version.created_by,
            version.change_reason,
            json.dumps(version.changed_fields, separators=(",", ":")),
        )

    def get_order_version(self, order_version_id: str) -> OrderVersion | None:
        row = self._conn.execute(
            "SELECT * FROM order_versions WHERE order_version_id = ?",
            (order_version_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_version(row)

    def list_order_versions(self, order_id: str) -> list[OrderVersion]:
        rows = self._conn.execute(
            "SELECT * FROM order_versions WHERE order_id = ? ORDER BY version_number",
            (order_id,),
        ).fetchall()
        return [self._row_to_version(r) for r in rows]

    @staticmethod
    def _row_to_version(row: tuple) -> OrderVersion:
        return OrderVersion(
            order_version_id=row[0],
            order_id=row[1],
            version_number=row[2],
            created_at=_dt(row[3]),
            event_date=date.fromisoformat(row[4]),
            time_window_text=row[5],
            location_text=row[6],
            guest_count_estimate=row[7],
            planning_mode=validate_planning_mode(row[8]),
            kitchen_print_confirmed_at=_dt(row[9]) if row[9] is not None else None,
            parent_order_version_id=row[10],
            created_by=row[11],
            change_reason=row[12],
            changed_fields=tuple(json.loads(row[13])),
        )
