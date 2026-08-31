from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path

from catering_system.domain.order import Order, OrderVersion
from catering_system.domain.order_payment_reminder import (
    OrderPaymentReminder,
    PaymentCompletionCorrection,
    PaymentMethodChange,
)
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


def test_payment_method_history_survives_restart(tmp_path: Path) -> None:
    db = tmp_path / "core.db"
    orders = SQLiteOrderRepository(db)
    order, version = _order("11111111-1111-4111-8111-111111111111")
    orders.save_order_with_initial_version(order, version)
    orders.close()

    reminders = SQLitePaymentReminderRepository(db)
    previous = OrderPaymentReminder(
        order_id=order.order_id,
        payment_method="RECHNUNG",
        invoice_created=True,
        invoice_number="RE-HISTORY-1",
        sent_on=date(2026, 7, 15),
        updated_at=datetime(2026, 7, 15, 8, 0, tzinfo=UTC),
        invoice_created_at=datetime(2026, 7, 15, 8, 0, tzinfo=UTC),
        invoice_created_by="Alice",
        invoice_sent_recorded_at=datetime(2026, 7, 15, 8, 5, tzinfo=UTC),
        invoice_sent_recorded_by="Alice",
    )
    current = OrderPaymentReminder(
        order_id=order.order_id,
        payment_method="BAR_VOR_ORT",
        updated_at=datetime(2026, 7, 16, 9, 0, tzinfo=UTC),
    )
    change = PaymentMethodChange(
        change_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        order_id=order.order_id,
        from_method="RECHNUNG",
        to_method="BAR_VOR_ORT",
        reason="Kunde zahlt bar",
        actor_reference="Bob",
        changed_at=datetime(2026, 7, 16, 9, 0, tzinfo=UTC),
        retired_task_title="Zahlungseingang prüfen",
        previous_reminder=previous,
    )

    reminders.save(previous)
    reminders.save_method_change(current, change)
    reminders.close()

    reminders = SQLitePaymentReminderRepository(db)
    assert reminders.get(order.order_id) == current
    assert reminders.list_method_changes(order.order_id) == (change,)
    reminders.close()


def test_payment_completion_correction_survives_restart(tmp_path: Path) -> None:
    db = tmp_path / "core.db"
    orders = SQLiteOrderRepository(db)
    order, version = _order("11111111-1111-4111-8111-111111111111")
    orders.save_order_with_initial_version(order, version)
    orders.close()

    reminders = SQLitePaymentReminderRepository(db)
    previous = OrderPaymentReminder(
        order_id=order.order_id,
        payment_method="RECHNUNG",
        invoice_created=True,
        invoice_number="RE-CORRECTION-1",
        sent_on=date(2026, 7, 1),
        paid_on=date(2026, 7, 15),
        updated_at=datetime(2026, 7, 15, 8, 0, tzinfo=UTC),
        invoice_created_at=datetime(2026, 7, 1, 8, 0, tzinfo=UTC),
        invoice_created_by="Alice",
        invoice_sent_recorded_at=datetime(2026, 7, 1, 8, 5, tzinfo=UTC),
        invoice_sent_recorded_by="Alice",
        paid_recorded_at=datetime(2026, 7, 15, 8, 0, tzinfo=UTC),
        paid_recorded_by="Alice",
    )
    current = OrderPaymentReminder(
        order_id=order.order_id,
        payment_method="RECHNUNG",
        invoice_created=True,
        invoice_number="RE-CORRECTION-1",
        sent_on=date(2026, 7, 1),
        updated_at=datetime(2026, 7, 16, 9, 0, tzinfo=UTC),
        invoice_created_at=previous.invoice_created_at,
        invoice_created_by="Alice",
        invoice_sent_recorded_at=previous.invoice_sent_recorded_at,
        invoice_sent_recorded_by="Alice",
    )
    correction = PaymentCompletionCorrection(
        correction_id="eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
        order_id=order.order_id,
        reason="Fehleingabe",
        actor_reference="Bob",
        corrected_at=datetime(2026, 7, 16, 9, 0, tzinfo=UTC),
        previous_reminder=previous,
    )

    reminders.save(previous)
    reminders.save_payment_correction(current, correction)
    reminders.close()

    reminders = SQLitePaymentReminderRepository(db)
    assert reminders.get(order.order_id) == current
    assert reminders.list_payment_corrections(order.order_id) == (correction,)
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
        invoice_created_at=datetime(2026, 7, 15, 8, 0, tzinfo=UTC),
        invoice_created_by="Alice",
        invoice_sent_recorded_at=datetime(2026, 7, 15, 8, 5, tzinfo=UTC),
        invoice_sent_recorded_by="Alice",
        payment_reminder_sent_at=datetime(2026, 7, 30, 9, 0, tzinfo=UTC),
        payment_reminder_sent_by="Bob",
        mahnung_sent_at=datetime(2026, 8, 6, 9, 0, tzinfo=UTC),
        mahnung_sent_by="Bob",
    )

    reminders.save(row)

    assert reminders.get(order.order_id) == row
    reminders.close()
    reminders = SQLitePaymentReminderRepository(db)
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
