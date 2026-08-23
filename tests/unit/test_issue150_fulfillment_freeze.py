"""Issue #150: fulfillment mode is frozen with the OrderVersion context."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

from catering_system.domain.customer_document_projection import CustomerAddress
from catering_system.domain.order import Order, OrderVersion
from catering_system.domain.order_operational_context import (
    OrderVersionOperationalContextSnapshot,
)
from catering_system.repositories.sqlite_order_repository import (
    SQLiteOrderRepository,
    _migration_9_operational_context_fulfillment_mode,
)
from tests.unit.test_order_confirmation_document import _effective_order, _services


def test_sqlite_operational_context_roundtrip_preserves_fulfillment_mode(
    tmp_path: Path,
) -> None:
    db = tmp_path / "orders.db"
    repo = SQLiteOrderRepository(db)
    created_at = datetime(2026, 8, 23, 6, 0, tzinfo=UTC)
    order = Order(
        order_id="order-freeze-1",
        source_inquiry_id="inquiry-freeze-1",
        created_at=created_at,
        updated_at=created_at,
    )
    version = OrderVersion(
        order_version_id="order-version-freeze-1",
        order_id=order.order_id,
        version_number=1,
        created_at=created_at,
        event_date=date(2026, 9, 1),
        time_window_text="12:00-14:00",
        location_text="Hamburg",
        guest_count_estimate=20,
        planning_mode="caterer_suggestion",
    )
    address = CustomerAddress(
        street="Eventweg 2",
        postal_code="20354",
        city="Hamburg",
        country="DE",
    )
    context = OrderVersionOperationalContextSnapshot(
        order_version_id=version.order_version_id,
        order_id=order.order_id,
        recipient_company="Freeze GmbH",
        recipient_name="Anna Freeze",
        recipient_phone="+4940123456",
        delivery_address=address,
        created_at=created_at,
        source="initial_inquiry_snapshot",
        fulfillment_mode="DELIVERY",
    )

    repo.save_order_with_initial_version(order, version, context)
    repo.close()

    reopened = SQLiteOrderRepository(db)
    loaded = reopened.get_operational_context(version.order_version_id)
    assert loaded is not None
    assert loaded.fulfillment_mode == "DELIVERY"
    assert loaded.delivery_address == address


def test_migration_9_keeps_existing_contexts_semantically_unknown(
    tmp_path: Path,
) -> None:
    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE order_version_operational_context_snapshots (
            order_version_id TEXT PRIMARY KEY,
            order_id TEXT NOT NULL,
            recipient_company TEXT,
            recipient_name TEXT,
            recipient_phone TEXT,
            delivery_address_json TEXT,
            created_at TEXT NOT NULL,
            source TEXT NOT NULL
        );
        INSERT INTO order_version_operational_context_snapshots (
            order_version_id, order_id, recipient_company, recipient_name,
            recipient_phone, delivery_address_json, created_at, source
        ) VALUES (
            'legacy-version', 'legacy-order', 'Legacy GmbH', 'Legacy User',
            '+4940999', NULL, '2026-08-01T10:00:00+00:00',
            'initial_inquiry_snapshot'
        );
        """
    )

    _migration_9_operational_context_fulfillment_mode(conn)

    columns = {
        row[1]
        for row in conn.execute(
            "PRAGMA table_info(order_version_operational_context_snapshots)"
        ).fetchall()
    }
    row = conn.execute(
        """
        SELECT order_version_id, fulfillment_mode
        FROM order_version_operational_context_snapshots
        WHERE order_version_id = 'legacy-version'
        """
    ).fetchone()
    assert "fulfillment_mode" in columns
    assert row == ("legacy-version", "UNKNOWN")


def test_confirmation_uses_frozen_mode_after_inquiry_changes() -> None:
    services = _services()
    order, version = _effective_order(services)
    inquiries = services[2]
    service = services[4]
    inquiry = inquiries.get_by_id(order.source_inquiry_id)
    assert inquiry is not None

    inquiries.update(replace(inquiry, fulfillment_mode="DELIVERY"))

    snapshot = service.prepare_snapshot(
        order.order_id,
        version.order_version_id,
        "office-panel",
    )

    assert snapshot.fulfillment_mode == "PICKUP"
    assert snapshot.delivery_address is None
