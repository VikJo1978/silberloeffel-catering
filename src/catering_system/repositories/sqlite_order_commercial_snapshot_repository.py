"""SQLite persistence for OrderCommercialSnapshot (append-only)."""

from __future__ import annotations

import json
import sqlite3
from contextlib import nullcontext
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from catering_system.domain.catalog import AllergenCode, validate_allergen_codes
from catering_system.domain.customer_document_projection import CustomerAddress
from catering_system.domain.inquiry import validate_fulfillment_mode
from catering_system.domain.inquiry_customer_snapshot import (
    customer_address_from_mapping,
    customer_address_to_mapping,
)
from catering_system.domain.offer import (
    POSITION_KINDS,
    POSITION_QUANTITY_MODES,
    VAT_RATES,
    PositionKind,
    PositionQuantityMode,
    VatRatePercent,
)
from catering_system.domain.order_commercial_snapshot import (
    OrderCommercialPosition,
    OrderCommercialSnapshot,
)
from catering_system.domain.order_payment_reminder import validate_payment_method
from catering_system.repositories.sqlite_migrations import apply_migrations


def _migration_1_create_tables(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE order_commercial_snapshots (
            snapshot_id TEXT PRIMARY KEY,
            order_id TEXT NOT NULL UNIQUE,
            source_offer_id TEXT NOT NULL,
            source_offer_version_id TEXT NOT NULL,
            source_variant_id TEXT NOT NULL,
            acceptance_id TEXT NOT NULL,
            accepted_at TEXT NOT NULL,
            recorded_by TEXT NOT NULL,
            variant_label TEXT NOT NULL,
            variant_description TEXT,
            payment_method TEXT NOT NULL,
            payment_customer_visible_text TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE order_commercial_positions (
            snapshot_id TEXT NOT NULL,
            position_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            name TEXT NOT NULL,
            unit_net_cents INTEGER NOT NULL,
            net_total_cents INTEGER NOT NULL,
            vat_rate_percent INTEGER NOT NULL,
            vat_amount_cents INTEGER NOT NULL,
            gross_total_cents INTEGER NOT NULL,
            related_position_id TEXT,
            description TEXT,
            composition TEXT,
            notes TEXT,
            quantity TEXT,
            quantity_mode TEXT,
            unit_label TEXT,
            catalog_item_id TEXT,
            allergens_json TEXT,
            PRIMARY KEY (snapshot_id, position_id),
            FOREIGN KEY (snapshot_id) REFERENCES order_commercial_snapshots(snapshot_id)
        );
        CREATE INDEX idx_order_commercial_snapshots_order_id
            ON order_commercial_snapshots (order_id);
        """
    )
    connection.executescript(
        """
        CREATE TRIGGER trg_order_commercial_snapshot_owner_insert
        BEFORE INSERT ON order_commercial_snapshots
        WHEN NOT EXISTS (
            SELECT 1 FROM orders WHERE order_id = NEW.order_id
        )
        BEGIN
            SELECT RAISE(ABORT, 'order commercial snapshot owner is invalid');
        END;
        CREATE TRIGGER trg_order_commercial_snapshot_immutable_update
        BEFORE UPDATE ON order_commercial_snapshots
        BEGIN
            SELECT RAISE(ABORT, 'order commercial snapshot is immutable');
        END;
        CREATE TRIGGER trg_order_commercial_snapshot_immutable_delete
        BEFORE DELETE ON order_commercial_snapshots
        BEGIN
            SELECT RAISE(ABORT, 'order commercial snapshot is immutable');
        END;
        CREATE TRIGGER trg_order_commercial_position_immutable_update
        BEFORE UPDATE ON order_commercial_positions
        BEGIN
            SELECT RAISE(ABORT, 'order commercial position is immutable');
        END;
        CREATE TRIGGER trg_order_commercial_position_immutable_delete
        BEFORE DELETE ON order_commercial_positions
        BEGIN
            SELECT RAISE(ABORT, 'order commercial position is immutable');
        END;
        """
    )


def _migration_2_add_fulfillment_context(connection: sqlite3.Connection) -> None:
    columns = {
        row[1]
        for row in connection.execute(
            "PRAGMA table_info(order_commercial_snapshots)"
        ).fetchall()
    }
    for name, declaration in (
        ("fulfillment_mode", "TEXT NOT NULL DEFAULT 'UNKNOWN'"),
        ("invoice_address_json", "TEXT"),
        ("delivery_address_json", "TEXT"),
    ):
        if name not in columns:
            connection.execute(
                f"ALTER TABLE order_commercial_snapshots ADD COLUMN {name} {declaration}"
            )


_MIGRATIONS = (
    (1, "create_order_commercial_snapshots", _migration_1_create_tables),
    (2, "add_fulfillment_context", _migration_2_add_fulfillment_context),
)


def _allergens_storage(value: tuple[str, ...] | None) -> str | None:
    if value is None:
        return None
    return json.dumps(list(value), ensure_ascii=False)


def _optional_allergens(value: str | None) -> tuple[AllergenCode, ...] | None:
    if value is None:
        return None
    parsed = json.loads(value)
    if not isinstance(parsed, list):
        raise ValueError("allergens_json must decode to a list")
    return validate_allergen_codes([str(item) for item in parsed])


def _address_storage(value: CustomerAddress | None) -> str | None:
    if value is None:
        return None
    return json.dumps(
        customer_address_to_mapping(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _optional_address(value: str | None) -> CustomerAddress | None:
    if value is None:
        return None
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("address JSON must decode to an object")
    return customer_address_from_mapping(parsed)


def _quantity_storage(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value, "f")


def _optional_quantity(value: str | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(value)


def _position_kind(value: str) -> PositionKind:
    if value not in POSITION_KINDS:
        raise ValueError("invalid position kind")
    return value


def _vat_rate(value: int) -> VatRatePercent:
    if value not in VAT_RATES:
        raise ValueError("vat_rate_percent must be 7 or 19")
    return value


def _position_quantity_mode(value: str | None) -> PositionQuantityMode | None:
    if value is None:
        return None
    if value not in POSITION_QUANTITY_MODES:
        raise ValueError("invalid stored quantity_mode")
    return value


class SQLiteOrderCommercialSnapshotRepository:
    def __init__(self, db_path: str | Path) -> None:
        self._conn = sqlite3.connect(str(db_path))
        self._manage_transactions = True
        try:
            apply_migrations(self._conn, "order_commercial_snapshots", _MIGRATIONS)
        except Exception:
            self._conn.close()
            raise

    @classmethod
    def from_connection(
        cls, connection: sqlite3.Connection
    ) -> SQLiteOrderCommercialSnapshotRepository:
        repo = cls.__new__(cls)
        repo._conn = connection
        repo._manage_transactions = False
        apply_migrations(connection, "order_commercial_snapshots", _MIGRATIONS)
        return repo

    def _write_scope(self):  # noqa: ANN202
        return self._conn if self._manage_transactions else nullcontext()

    def close(self) -> None:
        self._conn.close()

    def create(self, snapshot: OrderCommercialSnapshot) -> None:
        with self._write_scope():
            try:
                self._conn.execute(
                    """
                    INSERT INTO order_commercial_snapshots (
                        snapshot_id, order_id, source_offer_id, source_offer_version_id,
                        source_variant_id, acceptance_id, accepted_at, recorded_by,
                        variant_label, variant_description, payment_method,
                        payment_customer_visible_text, created_at, fulfillment_mode,
                        invoice_address_json, delivery_address_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        snapshot.snapshot_id,
                        snapshot.order_id,
                        snapshot.source_offer_id,
                        snapshot.source_offer_version_id,
                        snapshot.source_variant_id,
                        snapshot.acceptance_id,
                        snapshot.accepted_at.isoformat(),
                        snapshot.recorded_by,
                        snapshot.variant_label,
                        snapshot.variant_description,
                        snapshot.payment_method,
                        snapshot.payment_customer_visible_text,
                        snapshot.created_at.isoformat(),
                        snapshot.fulfillment_mode,
                        _address_storage(snapshot.invoice_address),
                        _address_storage(snapshot.delivery_address),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                text = str(exc).lower()
                if "unique" in text or "order_id" in text:
                    raise ValueError(
                        "order commercial snapshot already exists "
                        f"(order_id={snapshot.order_id!r})"
                    ) from exc
                raise
            for position in snapshot.positions:
                self._conn.execute(
                    """
                    INSERT INTO order_commercial_positions (
                        snapshot_id, position_id, kind, name,
                        unit_net_cents, net_total_cents, vat_rate_percent,
                        vat_amount_cents, gross_total_cents, related_position_id,
                        description, composition, notes, quantity, quantity_mode,
                        unit_label, catalog_item_id, allergens_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        snapshot.snapshot_id,
                        position.position_id,
                        position.kind,
                        position.name,
                        position.unit_net_cents,
                        position.net_total_cents,
                        position.vat_rate_percent,
                        position.vat_amount_cents,
                        position.gross_total_cents,
                        position.related_position_id,
                        position.description,
                        position.composition,
                        position.notes,
                        _quantity_storage(position.quantity),
                        position.quantity_mode,
                        position.unit_label,
                        position.catalog_item_id,
                        _allergens_storage(position.allergens),
                    ),
                )

    def get_by_order_id(self, order_id: str) -> OrderCommercialSnapshot | None:
        row = self._conn.execute(
            """
            SELECT snapshot_id FROM order_commercial_snapshots WHERE order_id = ?
            """,
            (order_id,),
        ).fetchone()
        if row is None:
            return None
        return self.get_by_id(row[0])

    def get_by_id(self, snapshot_id: str) -> OrderCommercialSnapshot | None:
        row = self._conn.execute(
            """
            SELECT snapshot_id, order_id, source_offer_id, source_offer_version_id,
                   source_variant_id, acceptance_id, accepted_at, recorded_by,
                   variant_label, variant_description, payment_method,
                   payment_customer_visible_text, created_at, fulfillment_mode,
                   invoice_address_json, delivery_address_json
            FROM order_commercial_snapshots WHERE snapshot_id = ?
            """,
            (snapshot_id,),
        ).fetchone()
        if row is None:
            return None
        positions = self._load_positions(snapshot_id)
        return OrderCommercialSnapshot(
            snapshot_id=row[0],
            order_id=row[1],
            source_offer_id=row[2],
            source_offer_version_id=row[3],
            source_variant_id=row[4],
            acceptance_id=row[5],
            accepted_at=datetime.fromisoformat(row[6]),
            recorded_by=row[7],
            variant_label=row[8],
            variant_description=row[9],
            payment_method=validate_payment_method(row[10]),
            payment_customer_visible_text=row[11],
            created_at=datetime.fromisoformat(row[12]),
            fulfillment_mode=validate_fulfillment_mode(row[13]),
            invoice_address=_optional_address(row[14]),
            delivery_address=_optional_address(row[15]),
            positions=positions,
        )

    def _load_positions(self, snapshot_id: str) -> tuple[OrderCommercialPosition, ...]:
        rows = self._conn.execute(
            """
            SELECT position_id, kind, name, unit_net_cents, net_total_cents,
                   vat_rate_percent, vat_amount_cents, gross_total_cents,
                   related_position_id, description, composition, notes,
                   quantity, quantity_mode, unit_label, catalog_item_id,
                   allergens_json
            FROM order_commercial_positions
            WHERE snapshot_id = ?
            ORDER BY rowid
            """,
            (snapshot_id,),
        ).fetchall()
        return tuple(
            OrderCommercialPosition(
                position_id=row[0],
                kind=_position_kind(row[1]),
                name=row[2],
                unit_net_cents=row[3],
                net_total_cents=row[4],
                vat_rate_percent=_vat_rate(row[5]),
                vat_amount_cents=row[6],
                gross_total_cents=row[7],
                related_position_id=row[8],
                description=row[9],
                composition=row[10],
                notes=row[11],
                quantity=_optional_quantity(row[12]),
                quantity_mode=_position_quantity_mode(row[13]),
                unit_label=row[14],
                catalog_item_id=row[15],
                allergens=_optional_allergens(row[16]),
            )
            for row in rows
        )
