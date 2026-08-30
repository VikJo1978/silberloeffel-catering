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
    assert view.next_step == "Rechnung erstellen/senden"
    assert view.due_on == date(2026, 7, 25)

    complete = replace(
        reminder,
        invoice_created=True,
        invoice_number="RE-2026-0048",
        sent_on=date(2026, 7, 20),
        # Legacy/manual values are deliberately ignored by the projection.
        due_on=date(2026, 7, 12),
    )
    urgent = derive_payment_reminder(
        complete, event_date=date(2026, 8, 1), today=date(2026, 7, 26)
    )
    assert urgent.due_on == date(2026, 7, 25)
    assert urgent.payment_state_label == "Sofort fällig"
    assert urgent.next_step == "Zahlungserinnerung senden"
    assert urgent.next_step_due_on == date(2026, 7, 26)

    overdue = derive_payment_reminder(
        complete, event_date=date(2026, 8, 1), today=date(2026, 8, 2)
    )
    assert overdue.payment_state_label == "Überfällig seit 8 Tagen"
    assert overdue.next_step == "Dringende manuelle Entscheidung erforderlich"
    assert overdue.next_step_due_on == date(2026, 7, 29)

    paid = derive_payment_reminder(
        replace(complete, paid_on=date(2026, 7, 27)),
        event_date=date(2026, 8, 1),
        today=date(2026, 7, 28),
    )
    assert paid.payment_state_label == "Bezahlt"
    assert paid.next_step is None


def test_rechnung_due_date_and_stages_are_system_derived() -> None:
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
    assert incomplete.due_on is None

    sent = replace(
        reminder,
        sent_on=date(2026, 7, 15),
        due_on=date(2026, 12, 31),
    )
    seven_days = derive_payment_reminder(
        sent, event_date=date(2026, 8, 1), today=date(2026, 7, 22)
    )
    assert seven_days.due_on == date(2026, 7, 29)
    assert seven_days.payment_state_label == "Fällig in 7 Tagen"

    three_days = derive_payment_reminder(
        sent, event_date=date(2026, 8, 1), today=date(2026, 7, 26)
    )
    assert three_days.payment_state_label == "Fällig in 3 Tagen"

    due_today = derive_payment_reminder(
        sent, event_date=date(2026, 8, 1), today=date(2026, 7, 29)
    )
    assert due_today.payment_state_label == "Heute fällig"

    overdue = derive_payment_reminder(
        sent, event_date=date(2026, 8, 1), today=date(2026, 7, 30)
    )
    assert overdue.payment_state_label == "Überfällig seit 1 Tag"
    assert overdue.next_step == "Zahlungserinnerung senden"
    assert overdue.next_step_due_on == date(2026, 7, 30)


def test_vorkasse_recorded_reminder_advances_to_manual_decision_boundary() -> None:
    reminder = OrderPaymentReminder(
        order_id="order",
        payment_method="VORKASSE",
        invoice_created=True,
        invoice_number="RE-V-1",
        sent_on=date(2026, 7, 20),
        payment_reminder_sent_at=datetime(2026, 7, 26, 8, 0, tzinfo=UTC),
        payment_reminder_sent_by="Alice",
    )

    waiting = derive_payment_reminder(
        reminder,
        event_date=date(2026, 8, 1),
        today=date(2026, 7, 27),
    )
    assert waiting.next_step == "Zahlungseingang prüfen"
    assert waiting.next_step_due_on == date(2026, 7, 29)

    urgent = derive_payment_reminder(
        reminder,
        event_date=date(2026, 8, 1),
        today=date(2026, 7, 29),
    )
    assert urgent.next_step == "Dringende manuelle Entscheidung erforderlich"
    assert urgent.next_step_due_on == date(2026, 7, 29)


def test_rechnung_escalation_audit_is_idempotent_and_drives_mahnung() -> None:
    orders, reminders, _service = _world()
    order_id = "11111111-1111-4111-8111-111111111111"
    invoice = OrderPaymentReminder(
        order_id=order_id,
        payment_method="RECHNUNG",
        invoice_created=True,
        invoice_number="RE-AUDIT-1",
        sent_on=date(2026, 7, 15),
    )
    reminder_now = datetime(2026, 7, 30, 8, 0, tzinfo=UTC)
    reminder_service = PaymentReminderService(
        reminders,
        orders,
        now=lambda: reminder_now,
        today=lambda: date(2026, 7, 30),
    )

    reminder_service.save(
        invoice,
        actor_reference="Alice",
        mark_payment_reminder_sent=True,
    )
    stored = reminders.get(order_id)
    assert stored is not None
    assert stored.invoice_created_at == reminder_now
    assert stored.invoice_created_by == "Alice"
    assert stored.invoice_sent_recorded_at == reminder_now
    assert stored.invoice_sent_recorded_by == "Alice"
    assert stored.payment_reminder_sent_at == reminder_now
    assert stored.payment_reminder_sent_by == "Alice"

    reminder_service.save(
        invoice,
        actor_reference="Bob",
        mark_payment_reminder_sent=True,
    )
    replayed = reminders.get(order_id)
    assert replayed == stored

    mahnung_now = datetime(2026, 8, 6, 9, 0, tzinfo=UTC)
    mahnung_service = PaymentReminderService(
        reminders,
        orders,
        now=lambda: mahnung_now,
        today=lambda: date(2026, 8, 6),
    )
    before_mahnung = mahnung_service.view(order_id)
    assert before_mahnung.next_step == "Mahnung senden"
    assert before_mahnung.next_step_due_on == date(2026, 8, 6)

    mahnung_service.save(
        invoice,
        actor_reference="Bob",
        mark_mahnung_sent=True,
    )
    after = reminders.get(order_id)
    assert after is not None
    assert after.mahnung_sent_at == mahnung_now
    assert after.mahnung_sent_by == "Bob"

    manual_service = PaymentReminderService(
        reminders,
        orders,
        now=lambda: datetime(2026, 8, 13, 9, 0, tzinfo=UTC),
        today=lambda: date(2026, 8, 13),
    )
    manual = manual_service.view(order_id)
    assert manual.next_step == "Manuelle Entscheidung erforderlich"
    assert manual.next_step_due_on == date(2026, 8, 13)


def test_quittung_print_audit_is_stamped_once() -> None:
    orders, reminders, _service = _world()
    order_id = "11111111-1111-4111-8111-111111111111"
    printed_at = datetime(2026, 7, 15, 10, 0, tzinfo=UTC)
    service = PaymentReminderService(
        reminders,
        orders,
        now=lambda: printed_at,
        today=lambda: date(2026, 7, 15),
    )
    row = OrderPaymentReminder(
        order_id=order_id,
        payment_method="BAR_VOR_ORT",
        quittung_printed=True,
    )

    service.save(row, actor_reference="Alice")
    first = reminders.get(order_id)
    assert first is not None
    assert first.quittung_printed_at == printed_at
    assert first.quittung_printed_by == "Alice"

    service.save(row, actor_reference="Bob")
    assert reminders.get(order_id) == first



def test_cash_quittung_is_required_before_collection_wait_state() -> None:
    reminder = OrderPaymentReminder(order_id="order", payment_method="BAR_VOR_ORT")
    before_print = derive_payment_reminder(
        reminder, event_date=date(2026, 7, 20), today=date(2026, 7, 15)
    )
    assert before_print.next_step == "Quittung vorbereiten/drucken"

    printed = replace(reminder, quittung_printed=True)
    before_event = derive_payment_reminder(
        printed, event_date=date(2026, 7, 20), today=date(2026, 7, 15)
    )
    assert before_event.next_step == "Barzahlung vor Ort abwarten"

    after = derive_payment_reminder(
        printed, event_date=date(2026, 7, 20), today=date(2026, 7, 21)
    )
    assert after.next_step == "Barzahlung klären"

    with pytest.raises(ValueError, match="recorded together"):
        validate_payment_reminder(replace(printed, cash_received=True))
    paid = derive_payment_reminder(
        replace(
            printed,
            cash_received=True,
            paid_on=date(2026, 7, 20),
        ),
        event_date=date(2026, 7, 20),
        today=date(2026, 7, 21),
    )
    assert paid.payment_state_label == "Bezahlt"


def test_quittung_readiness_is_cash_only() -> None:
    with pytest.raises(ValueError, match="quittung readiness"):
        validate_payment_reminder(
            OrderPaymentReminder(
                order_id="order",
                payment_method="RECHNUNG",
                quittung_printed=True,
            )
        )


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


def test_conversion_seed_is_idempotent_and_rejects_a_different_choice() -> None:
    _orders, reminders, service = _world()
    order_id = "11111111-1111-4111-8111-111111111111"

    service.seed_from_conversion(order_id, "VORKASSE")
    service.seed_from_conversion(order_id, "VORKASSE")

    stored = reminders.get(order_id)
    assert stored is not None
    assert stored.payment_method == "VORKASSE"
    assert stored.updated_at == _NOW
    with pytest.raises(ValueError, match="conflicts with existing"):
        service.seed_from_conversion(order_id, "RECHNUNG")
    assert reminders.get(order_id) == stored


def test_service_discards_legacy_manual_due_date() -> None:
    _orders, reminders, service = _world()
    order_id = "11111111-1111-4111-8111-111111111111"
    service.save(
        OrderPaymentReminder(
            order_id=order_id,
            payment_method="RECHNUNG",
            invoice_created=True,
            invoice_number="RE-1",
            sent_on=date(2026, 7, 15),
            due_on=date(2030, 1, 1),
        )
    )

    stored = reminders.get(order_id)
    assert stored is not None
    assert stored.due_on is None
    assert service.view(order_id).due_on == date(2026, 7, 29)


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
