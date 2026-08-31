"""SQLite order repository — same OrderRepository Protocol as the in-memory baseline.

Persistence adapter only: no business rules, no new truth axis. Schema mirrors
the frozen Order/OrderVersion field set (incl. the two OPERATIONAL_CORE §7 fields).
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import nullcontext
from dataclasses import replace
from datetime import date, datetime, time
from pathlib import Path

from catering_system.domain.customer_document_projection import CustomerAddress
from catering_system.domain.inquiry import (
    validate_fulfillment_mode,
    validate_planning_mode,
)
from catering_system.domain.inquiry_customer_snapshot import (
    customer_address_from_mapping,
    customer_address_to_mapping,
)
from catering_system.domain.order import Order, OrderVersion
from catering_system.domain.order_operational_context import (
    ORDER_OPERATIONAL_CONTEXT_SOURCES,
    OrderVersionOperationalContextSnapshot,
)
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


def _create_operational_context_table(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS order_version_operational_context_snapshots (
            order_version_id TEXT PRIMARY KEY,
            order_id TEXT NOT NULL,
            recipient_company TEXT,
            recipient_name TEXT,
            recipient_phone TEXT,
            delivery_address_json TEXT,
            created_at TEXT NOT NULL,
            source TEXT NOT NULL,
            fulfillment_mode TEXT NOT NULL DEFAULT 'UNKNOWN',
            CHECK (
                source IN (
                    'initial_inquiry_snapshot',
                    'inherited_parent',
                    'explicit_change',
                    'confirmation_snapshot_backfill'
                )
            ),
            CHECK (fulfillment_mode IN ('UNKNOWN', 'DELIVERY', 'PICKUP')),
            FOREIGN KEY (order_version_id) REFERENCES order_versions(order_version_id),
            FOREIGN KEY (order_id) REFERENCES orders(order_id)
        );
        CREATE TRIGGER IF NOT EXISTS trg_order_version_operational_context_owner_insert
        BEFORE INSERT ON order_version_operational_context_snapshots
        WHEN NOT EXISTS (
            SELECT 1 FROM order_versions v
            WHERE v.order_version_id = NEW.order_version_id
              AND v.order_id = NEW.order_id
        )
        BEGIN
            SELECT RAISE(ABORT, 'order version operational context owner is invalid');
        END;
        CREATE TRIGGER IF NOT EXISTS trg_order_version_operational_context_immutable_update
        BEFORE UPDATE ON order_version_operational_context_snapshots
        BEGIN
            SELECT RAISE(ABORT, 'order version operational context is immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS trg_order_version_operational_context_immutable_delete
        BEFORE DELETE ON order_version_operational_context_snapshots
        BEGIN
            SELECT RAISE(ABORT, 'order version operational context is immutable');
        END;
        """
    )


def _backfill_operational_context_from_confirmations(
    connection: sqlite3.Connection,
) -> None:
    exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' "
        "AND name = 'order_confirmation_document_snapshots'"
    ).fetchone()
    if exists is None:
        return
    rows = connection.execute(
        """
        SELECT d.canonical_snapshot_json
        FROM order_confirmation_document_snapshots d
        JOIN order_versions v ON v.order_version_id = d.order_version_id
        LEFT JOIN order_version_operational_context_snapshots c
          ON c.order_version_id = d.order_version_id
        WHERE c.order_version_id IS NULL
        """
    ).fetchall()
    for (raw,) in rows:
        payload = json.loads(raw)
        delivery_address = payload.get("delivery_address")
        try:
            fulfillment_mode = validate_fulfillment_mode(
                str(payload.get("fulfillment_mode", "UNKNOWN"))
            )
        except ValueError:
            fulfillment_mode = "UNKNOWN"
        connection.execute(
            """
            INSERT OR IGNORE INTO order_version_operational_context_snapshots (
                order_version_id,
                order_id,
                recipient_company,
                recipient_name,
                recipient_phone,
                delivery_address_json,
                created_at,
                source,
                fulfillment_mode
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(payload["order_version_id"]),
                str(payload["order_id"]),
                _optional_text(payload.get("recipient_company")),
                _optional_text(payload.get("recipient_name")),
                _optional_text(payload.get("recipient_phone")),
                (
                    json.dumps(delivery_address, ensure_ascii=False, sort_keys=True)
                    if delivery_address is not None
                    else None
                ),
                str(payload["created_at"]),
                "confirmation_snapshot_backfill",
                fulfillment_mode,
            ),
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


def _migration_8_operational_context_snapshots(connection: sqlite3.Connection) -> None:
    _create_operational_context_table(connection)
    _backfill_operational_context_from_confirmations(connection)


def _migration_9_operational_context_fulfillment_mode(
    connection: sqlite3.Connection,
) -> None:
    columns = {
        row[1]
        for row in connection.execute(
            "PRAGMA table_info(order_version_operational_context_snapshots)"
        ).fetchall()
    }
    if "fulfillment_mode" not in columns:
        connection.execute(
            "ALTER TABLE order_version_operational_context_snapshots "
            "ADD COLUMN fulfillment_mode TEXT NOT NULL DEFAULT 'UNKNOWN' "
            "CHECK (fulfillment_mode IN ('UNKNOWN', 'DELIVERY', 'PICKUP'))"
        )


def _migration_10_order_version_logistics_timing(
    connection: sqlite3.Connection,
) -> None:
    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(order_versions)")
    }
    for name in (
        "delivery_date_local",
        "delivery_window_start_local",
        "delivery_window_end_local",
    ):
        if name not in columns:
            connection.execute(f"ALTER TABLE order_versions ADD COLUMN {name} TEXT")
    connection.execute(
        """CREATE TRIGGER IF NOT EXISTS trg_order_version_logistics_timing_immutable
        BEFORE UPDATE OF delivery_date_local, delivery_window_start_local,
                         delivery_window_end_local ON order_versions
        WHEN NEW.delivery_date_local IS NOT OLD.delivery_date_local
          OR NEW.delivery_window_start_local IS NOT OLD.delivery_window_start_local
          OR NEW.delivery_window_end_local IS NOT OLD.delivery_window_end_local
        BEGIN SELECT RAISE(ABORT, 'order version logistics timing is immutable'); END"""
    )


def _migration_11_order_version_exact_timing(
    connection: sqlite3.Connection,
) -> None:
    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(order_versions)")
    }
    for name in ("event_start_local", "delivery_time_local"):
        if name not in columns:
            connection.execute(f"ALTER TABLE order_versions ADD COLUMN {name} TEXT")
    connection.execute(
        """CREATE TRIGGER IF NOT EXISTS trg_order_version_exact_timing_immutable
        BEFORE UPDATE OF event_start_local, delivery_time_local ON order_versions
        WHEN NEW.event_start_local IS NOT OLD.event_start_local
          OR NEW.delivery_time_local IS NOT OLD.delivery_time_local
        BEGIN SELECT RAISE(ABORT, 'order version exact timing is immutable'); END"""
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
    (
        8,
        "operational_context_snapshots",
        _migration_8_operational_context_snapshots,
    ),
    (
        9,
        "operational_context_fulfillment_mode",
        _migration_9_operational_context_fulfillment_mode,
    ),
    (
        10,
        "order_version_logistics_timing",
        _migration_10_order_version_logistics_timing,
    ),
    (
        11,
        "order_version_exact_timing",
        _migration_11_order_version_exact_timing,
    ),
)


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _address_json(address: CustomerAddress | None) -> str | None:
    if address is None:
        return None
    return json.dumps(
        customer_address_to_mapping(address),
        ensure_ascii=False,
        sort_keys=True,
    )


def _address_from_json(raw: str | None) -> CustomerAddress | None:
    if raw is None:
        return None
    return customer_address_from_mapping(json.loads(raw))


class SQLiteOrderRepository:
    def __init__(self, db_path: str | Path) -> None:
        self._conn = sqlite3.connect(str(db_path))
        self._manage_transactions = True
        try:
            apply_migrations(self._conn, "orders", _MIGRATIONS)
            _backfill_operational_context_from_confirmations(self._conn)
            if self._conn.in_transaction:
                self._conn.commit()
        except Exception:
            if self._conn.in_transaction:
                self._conn.rollback()
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
        _backfill_operational_context_from_confirmations(connection)
        return repo

    def _write_scope(self):
        # `with self._write_scope():` commits on exit — correct standalone, fatal
        # inside an externally-owned transaction (it would commit half a
        # command). nullcontext leaves control with the coordinator.
        return self._conn if self._manage_transactions else nullcontext()

    def close(self) -> None:
        self._conn.close()

    def save_order_with_initial_version(
        self,
        order: Order,
        version: OrderVersion,
        operational_context: OrderVersionOperationalContextSnapshot | None = None,
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
                """
                INSERT INTO order_versions (
                    order_version_id, order_id, version_number, created_at,
                    event_date, time_window_text, location_text, guest_count_estimate,
                    planning_mode, kitchen_print_confirmed_at, parent_order_version_id,
                    created_by, change_reason, changed_fields_json, delivery_date_local,
                    delivery_window_start_local, delivery_window_end_local,
                    event_start_local, delivery_time_local
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._version_values(version),
            )
            if operational_context is not None:
                self._insert_operational_context(version, operational_context)

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

    def append_order_version(
        self,
        order: Order,
        version: OrderVersion,
        operational_context: OrderVersionOperationalContextSnapshot | None = None,
    ) -> None:
        """Append a version and update its aggregate root in one transaction."""
        if version.order_id != order.order_id or version.version_number < 1:
            raise ValueError("version must belong to the supplied order")
        with self._write_scope():
            self._conn.execute(
                """
                INSERT INTO order_versions (
                    order_version_id, order_id, version_number, created_at,
                    event_date, time_window_text, location_text, guest_count_estimate,
                    planning_mode, kitchen_print_confirmed_at, parent_order_version_id,
                    created_by, change_reason, changed_fields_json, delivery_date_local,
                    delivery_window_start_local, delivery_window_end_local,
                    event_start_local, delivery_time_local
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._version_values(version),
            )
            if operational_context is not None:
                self._insert_operational_context(version, operational_context)
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

    def _insert_operational_context(
        self,
        version: OrderVersion,
        context: OrderVersionOperationalContextSnapshot,
    ) -> None:
        if (
            context.order_version_id != version.order_version_id
            or context.order_id != version.order_id
        ):
            raise ValueError("operational context owner is invalid")
        if context.source not in ORDER_OPERATIONAL_CONTEXT_SOURCES:
            raise ValueError("invalid operational context source")
        self._conn.execute(
            """
            INSERT INTO order_version_operational_context_snapshots (
                order_version_id,
                order_id,
                recipient_company,
                recipient_name,
                recipient_phone,
                delivery_address_json,
                created_at,
                source,
                fulfillment_mode
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                context.order_version_id,
                context.order_id,
                context.recipient_company,
                context.recipient_name,
                context.recipient_phone,
                _address_json(context.delivery_address),
                context.created_at.isoformat(),
                context.source,
                context.fulfillment_mode,
            ),
        )

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
            (
                version.delivery_date_local.isoformat()
                if version.delivery_date_local is not None
                else None
            ),
            (
                version.delivery_window_start_local.isoformat(timespec="minutes")
                if version.delivery_window_start_local is not None
                else None
            ),
            (
                version.delivery_window_end_local.isoformat(timespec="minutes")
                if version.delivery_window_end_local is not None
                else None
            ),
            (
                version.event_start_local.isoformat(timespec="minutes")
                if version.event_start_local is not None
                else None
            ),
            (
                version.delivery_time_local.isoformat(timespec="minutes")
                if version.delivery_time_local is not None
                else None
            ),
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

    def get_operational_context(
        self, order_version_id: str
    ) -> OrderVersionOperationalContextSnapshot | None:
        row = self._conn.execute(
            """
            SELECT order_version_id, order_id, recipient_company, recipient_name,
                   recipient_phone, delivery_address_json, created_at, source,
                   fulfillment_mode
            FROM order_version_operational_context_snapshots
            WHERE order_version_id = ?
            """,
            (order_version_id,),
        ).fetchone()
        if row is None:
            return None
        source = row[7]
        if source not in ORDER_OPERATIONAL_CONTEXT_SOURCES:
            raise ValueError("invalid operational context source")
        return OrderVersionOperationalContextSnapshot(
            order_version_id=row[0],
            order_id=row[1],
            recipient_company=row[2],
            recipient_name=row[3],
            recipient_phone=row[4],
            delivery_address=_address_from_json(row[5]),
            created_at=_dt(row[6]),
            source=source,
            fulfillment_mode=validate_fulfillment_mode(row[8]),
        )

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
            delivery_date_local=(
                date.fromisoformat(row[14]) if row[14] is not None else None
            ),
            delivery_window_start_local=(
                time.fromisoformat(row[15]) if row[15] is not None else None
            ),
            delivery_window_end_local=(
                time.fromisoformat(row[16]) if row[16] is not None else None
            ),
            event_start_local=(
                time.fromisoformat(row[17]) if row[17] is not None else None
            ),
            delivery_time_local=(
                time.fromisoformat(row[18]) if row[18] is not None else None
            ),
        )
