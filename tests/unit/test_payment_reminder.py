from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from catering_system.domain.order import Order, OrderVersion
from catering_system.domain.order_payment_reminder import (
    OrderPaymentReminder,
    derive_payment_reminder,
    validate_payment_reminder,
)
from catering_system.repositories.in_memory_order_repository import (
    InMemoryOrderRepository,
)
from catering_system.repositories.in_memory_payment_reminder_repository import (
    InMemoryPaymentReminderRepository,
)
from catering_system.services.payment_reminder_service import PaymentReminderService

_NOW = datetime(2026, 7, 15, 8, 30, tzinfo=UTC)


def _world() -> tuple[
    InMemoryOrderRepository, InMemoryPaymentReminderRepository, PaymentReminderService
]:
    orders = InMemoryOrderRepository()
    order = Order(
        order_id="11111111-1111-4111-8111-111111111111",
        source_inquiry_id="22222222-2222-4222-8222-222222222222",
        created_at=_NOW,
        updated_at=_NOW,
    )
    version = OrderVersion(
        order_version_id="33333333-3333-4333-8333-333333333333",
        order_id=order.order_id,
        version_number=1,
        created_at=_NOW,
        event_date=date(2026, 7, 20),
        time_window_text="mittags",
        location_text="Hamburg",
        guest_count_estimate=20,
        planning_mode="caterer_suggestion",
    )
    orders.save_order_with_initial_version(order, version)
    reminders = InMemoryPaymentReminderRepository()
    service = PaymentReminderService(
        reminders,
        orders,
        now=lambda: _NOW,
        today=lambda: date(2026, 7, 15),
    )
    return orders, reminders, service


def test_legacy_order_without_reminder_derives_selection_task() -> None:
    _orders, _reminders, service = _world()

    view = service.view("11111111-1111-4111-8111-111111111111")

    assert view.payment_method is None
    assert view.payment_method_label == "Noch nicht gewählt"
    assert view.next_step == "Zahlungsart auswählen"


def test_vorkasse_progression_and_overdue_are_purely_derived() -> None:
    reminder = OrderPaymentReminder(
        order_id="order",
        payment_method="VORKASSE",
    )
    view = derive_payment_reminder(
        reminder, event_date=date(2026, 8, 1), today=date(2026, 7, 15)
    )
    assert view.next_step == "Vorauszahlungsrechnung in der Buchhaltung erstellen"

    complete = replace(
        reminder,
        invoice_created=True,
        invoice_number="RE-2026-0048",
        sent_on=date(2026, 7, 10),
        due_on=date(2026, 7, 12),
    )
    overdue = derive_payment_reminder(
        complete, event_date=date(2026, 8, 1), today=date(2026, 7, 15)
    )
    assert overdue.payment_state_label == "Überfällig seit 3 Tagen"
    assert overdue.next_step == "Zahlung überfällig"

    one_day = derive_payment_reminder(
        complete, event_date=date(2026, 8, 1), today=date(2026, 7, 13)
    )
    assert one_day.payment_state_label == "Überfällig seit 1 Tag"

    paid = derive_payment_reminder(
        replace(complete, paid_on=date(2026, 7, 14)),
        event_date=date(2026, 8, 1),
        today=date(2026, 7, 15),
    )
    assert paid.payment_state_label == "Bezahlt"
    assert paid.next_step is None


def test_rechnung_requires_external_invoice_data_before_payment_check() -> None:
    reminder = OrderPaymentReminder(
        order_id="order",
        payment_method="RECHNUNG",
        invoice_created=True,
        invoice_number="RE-1",
    )
    incomplete = derive_payment_reminder(
        reminder, event_date=date(2026, 8, 1), today=date(2026, 7, 15)
    )
    assert incomplete.next_step == "Rechnungsdaten vervollständigen"

    open_view = derive_payment_reminder(
        replace(
            reminder,
            sent_on=date(2026, 7, 15),
            due_on=date(2026, 7, 22),
        ),
        event_date=date(2026, 8, 1),
        today=date(2026, 7, 15),
    )
    assert open_view.payment_state_label == "Offen"
    assert open_view.next_step == "Zahlungseingang prüfen"


def test_cash_reminder_changes_after_event_and_requires_paid_date() -> None:
    reminder = OrderPaymentReminder(order_id="order", payment_method="BAR_VOR_ORT")
    before = derive_payment_reminder(
        reminder, event_date=date(2026, 7, 20), today=date(2026, 7, 15)
    )
    assert before.next_step == "Barzahlung vor Ort abwarten"

    after = derive_payment_reminder(
        reminder, event_date=date(2026, 7, 20), today=date(2026, 7, 21)
    )
    assert after.next_step == "Barzahlung bestätigen"

    with pytest.raises(ValueError, match="recorded together"):
        validate_payment_reminder(replace(reminder, cash_received=True))
    paid = derive_payment_reminder(
        replace(reminder, cash_received=True, paid_on=date(2026, 7, 20)),
        event_date=date(2026, 7, 20),
        today=date(2026, 7, 21),
    )
    assert paid.payment_state_label == "Bezahlt"


def test_save_is_idempotent_and_does_not_modify_operational_order() -> None:
    orders, reminders, service = _world()
    order_before = orders.get_order("11111111-1111-4111-8111-111111111111")
    reminder = OrderPaymentReminder(
        order_id="11111111-1111-4111-8111-111111111111",
        payment_method="RECHNUNG",
    )

    first = service.save(reminder)
    second = service.save(reminder)

    assert first.updated_at == second.updated_at == _NOW
    assert reminders.get(reminder.order_id) is not None
    assert orders.get_order(reminder.order_id) == order_before


def test_payment_method_cannot_change_after_downstream_facts() -> None:
    _orders, _reminders, service = _world()
    order_id = "11111111-1111-4111-8111-111111111111"
    service.save(
        OrderPaymentReminder(
            order_id=order_id,
            payment_method="RECHNUNG",
            invoice_created=True,
            invoice_number="RE-1",
        )
    )

    with pytest.raises(ValueError, match="cannot change"):
        service.save(
            OrderPaymentReminder(order_id=order_id, payment_method="BAR_VOR_ORT")
        )


def test_cancelled_order_cannot_update_reminder() -> None:
    orders, _reminders, service = _world()
    order = orders.get_order("11111111-1111-4111-8111-111111111111")
    assert order is not None
    orders.update_order(replace(order, cancelled_at=_NOW))

    with pytest.raises(ValueError, match="cancelled"):
        service.save(
            OrderPaymentReminder(order_id=order.order_id, payment_method="VORKASSE")
        )
