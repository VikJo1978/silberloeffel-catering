from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path

from catering_system.domain.order import Order, OrderVersion
from catering_system.domain.order_payment_reminder import OrderPaymentReminder
from catering_system.repositories.sqlite_order_repository import SQLiteOrderRepository
from catering_system.repositories.sqlite_payment_reminder_repository import (
    SQLitePaymentReminderRepository,
)


def _order(order_id: str) -> tuple[Order, OrderVersion]:
    now = datetime(2026, 7, 15, tzinfo=UTC)
    return (
        Order(
            order_id=order_id,
            source_inquiry_id="22222222-2222-4222-8222-222222222222",
            created_at=now,
            updated_at=now,
        ),
        OrderVersion(
            order_version_id="33333333-3333-4333-8333-333333333333",
            order_id=order_id,
            version_number=1,
            created_at=now,
            event_date=date(2026, 8, 1),
            time_window_text="mittags",
            location_text="Hamburg",
            guest_count_estimate=20,
            planning_mode="caterer_suggestion",
        ),
    )


def test_additive_migration_keeps_existing_order_without_financial_data(
    tmp_path: Path,
) -> None:
    db = tmp_path / "core.db"
    orders = SQLiteOrderRepository(db)
    order, version = _order("11111111-1111-4111-8111-111111111111")
    orders.save_order_with_initial_version(order, version)
    orders.close()

    reminders = SQLitePaymentReminderRepository(db)

    assert reminders.get(order.order_id) is None
    reminders.close()


def test_sqlite_round_trip_and_owner_constraint(tmp_path: Path) -> None:
    db = tmp_path / "core.db"
    orders = SQLiteOrderRepository(db)
    order, version = _order("11111111-1111-4111-8111-111111111111")
    orders.save_order_with_initial_version(order, version)
    orders.close()
    reminders = SQLitePaymentReminderRepository(db)
    row = OrderPaymentReminder(
        order_id=order.order_id,
        payment_method="RECHNUNG",
        invoice_created=True,
        invoice_number="RE-2026-1",
        sent_on=date(2026, 7, 15),
        due_on=date(2026, 7, 22),
        updated_at=datetime(2026, 7, 15, tzinfo=UTC),
    )

    reminders.save(row)

    assert reminders.get(order.order_id) == row
    orphan = OrderPaymentReminder(
        order_id="99999999-9999-4999-8999-999999999999",
        payment_method="VORKASSE",
        updated_at=datetime(2026, 7, 15, tzinfo=UTC),
    )
    try:
        reminders.save(orphan)
    except sqlite3.IntegrityError:
        pass
    else:
        raise AssertionError("orphan payment reminder was accepted")
    reminders.close()
