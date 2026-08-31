from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from catering_system.domain.order import Order, OrderVersion
from catering_system.domain.order_payment_reminder import (
    OrderPaymentReminder,
    PaymentCompletionCorrection,
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


def _append_revision(
    orders: InMemoryOrderRepository,
    *,
    created_at: datetime,
) -> OrderVersion:
    order_id = "11111111-1111-4111-8111-111111111111"
    current = orders.get_order(order_id)
    assert current is not None
    source = orders.list_order_versions(order_id)[0]
    revision = OrderVersion(
        order_version_id="44444444-4444-4444-8444-444444444444",
        order_id=order_id,
        version_number=2,
        created_at=created_at,
        event_date=date(2026, 7, 21),
        time_window_text="abends",
        location_text="Hamburg",
        guest_count_estimate=25,
        planning_mode="caterer_suggestion",
        parent_order_version_id=source.order_version_id,
        created_by="Office",
        change_reason="Kunde hat den Auftrag geändert",
        changed_fields=("event_date", "guest_count_estimate"),
    )
    orders.append_order_version(
        replace(
            current,
            candidate_order_version_id=revision.order_version_id,
            updated_at=created_at,
        ),
        revision,
    )
    return revision


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


def test_direct_save_cannot_silently_change_payment_method() -> None:
    _orders, _reminders, service = _world()
    order_id = "11111111-1111-4111-8111-111111111111"
    service.save(OrderPaymentReminder(order_id=order_id, payment_method="RECHNUNG"))

    with pytest.raises(ValueError, match="explicit command"):
        service.save(
            OrderPaymentReminder(order_id=order_id, payment_method="BAR_VOR_ORT")
        )


def test_explicit_payment_method_change_archives_facts_and_resets_workflow() -> None:
    _orders, reminders, service = _world()
    order_id = "11111111-1111-4111-8111-111111111111"
    service.save(
        OrderPaymentReminder(
            order_id=order_id,
            payment_method="RECHNUNG",
            invoice_created=True,
            invoice_number="RE-OLD-1",
            sent_on=date(2026, 7, 15),
        ),
        actor_reference="Alice",
    )

    changed = service.change_payment_method(
        order_id,
        new_payment_method="BAR_VOR_ORT",
        reason="Kunde zahlt bei Abholung bar",
        actor_reference="Bob",
    )

    assert changed.payment_method == "BAR_VOR_ORT"
    assert changed.invoice_created is False
    assert changed.invoice_number is None
    assert changed.sent_on is None
    assert changed.quittung_printed is False
    assert changed.next_step == "Quittung vorbereiten/drucken"
    assert len(changed.method_changes) == 1

    event = changed.method_changes[0]
    assert event.from_method == "RECHNUNG"
    assert event.to_method == "BAR_VOR_ORT"
    assert event.reason == "Kunde zahlt bei Abholung bar"
    assert event.actor_reference == "Bob"
    assert event.changed_at == _NOW
    assert event.retired_task_title == "Zahlungseingang prüfen"
    assert event.previous_reminder.invoice_number == "RE-OLD-1"
    assert event.previous_reminder.invoice_created_by == "Alice"
    assert reminders.get(order_id) is not None
    assert reminders.get(order_id).payment_method == "BAR_VOR_ORT"


def test_payment_method_change_requires_reason_and_different_method() -> None:
    _orders, _reminders, service = _world()
    order_id = "11111111-1111-4111-8111-111111111111"
    service.save(OrderPaymentReminder(order_id=order_id, payment_method="VORKASSE"))

    with pytest.raises(ValueError, match="reason"):
        service.change_payment_method(
            order_id,
            new_payment_method="RECHNUNG",
            reason=" ",
            actor_reference="Alice",
        )
    with pytest.raises(ValueError, match="must differ"):
        service.change_payment_method(
            order_id,
            new_payment_method="VORKASSE",
            reason="Korrektur",
            actor_reference="Alice",
        )


def test_payment_method_change_after_payment_is_forbidden() -> None:
    _orders, _reminders, service = _world()
    order_id = "11111111-1111-4111-8111-111111111111"
    service.save(
        OrderPaymentReminder(
            order_id=order_id,
            payment_method="RECHNUNG",
            invoice_created=True,
            invoice_number="RE-PAID-1",
            sent_on=date(2026, 7, 1),
            paid_on=date(2026, 7, 15),
        ),
        actor_reference="Alice",
    )

    with pytest.raises(ValueError, match="after payment"):
        service.change_payment_method(
            order_id,
            new_payment_method="BAR_VOR_ORT",
            reason="Zu spät bemerkt",
            actor_reference="Bob",
        )


def test_payment_completion_correction_preserves_invoice_payment_audit() -> None:
    _orders, reminders, service = _world()
    order_id = "11111111-1111-4111-8111-111111111111"
    service.save(
        OrderPaymentReminder(
            order_id=order_id,
            payment_method="RECHNUNG",
            invoice_created=True,
            invoice_number="RE-CORRECT-1",
            sent_on=date(2026, 7, 1),
            paid_on=date(2026, 7, 15),
        ),
        actor_reference="Alice",
    )
    before = reminders.get(order_id)
    assert before is not None
    assert before.paid_recorded_at == _NOW
    assert before.paid_recorded_by == "Alice"

    corrected = service.correct_payment_completion(
        order_id,
        correction_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        reason="Zahlung versehentlich als eingegangen markiert",
        actor_reference="Bob",
    )

    assert corrected.paid_on is None
    assert corrected.cash_received is False
    assert corrected.paid_recorded_at is None
    assert corrected.payment_state_label != "Bezahlt"
    assert len(corrected.payment_corrections) == 1
    event = corrected.payment_corrections[0]
    assert event.reason == "Zahlung versehentlich als eingegangen markiert"
    assert event.actor_reference == "Bob"
    assert event.corrected_at == _NOW
    assert event.previous_reminder.paid_on == date(2026, 7, 15)
    assert event.previous_reminder.paid_recorded_at == _NOW
    assert event.previous_reminder.paid_recorded_by == "Alice"


def test_payment_completion_correction_is_idempotent_by_correction_id() -> None:
    _orders, _reminders, service = _world()
    order_id = "11111111-1111-4111-8111-111111111111"
    service.save(
        OrderPaymentReminder(
            order_id=order_id,
            payment_method="RECHNUNG",
            invoice_created=True,
            invoice_number="RE-CORRECT-2",
            sent_on=date(2026, 7, 1),
            paid_on=date(2026, 7, 15),
        ),
        actor_reference="Alice",
    )
    correction_id = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"

    first = service.correct_payment_completion(
        order_id,
        correction_id=correction_id,
        reason="Fehleingabe",
        actor_reference="Bob",
    )
    replay = service.correct_payment_completion(
        order_id,
        correction_id=correction_id,
        reason="Fehleingabe",
        actor_reference="Bob",
    )

    assert replay == first
    assert len(replay.payment_corrections) == 1

    with pytest.raises(ValueError, match="id conflict"):
        service.correct_payment_completion(
            order_id,
            correction_id=correction_id,
            reason="Anderer Grund",
            actor_reference="Bob",
        )


def test_payment_completion_correction_requires_recorded_payment() -> None:
    _orders, _reminders, service = _world()
    order_id = "11111111-1111-4111-8111-111111111111"
    service.save(OrderPaymentReminder(order_id=order_id, payment_method="RECHNUNG"))

    with pytest.raises(ValueError, match="not recorded"):
        service.correct_payment_completion(
            order_id,
            correction_id="cccccccc-cccc-4ccc-8ccc-cccccccccccc",
            reason="Fehleingabe",
            actor_reference="Alice",
        )


def test_cash_payment_completion_correction_restores_open_cash_state() -> None:
    _orders, _reminders, service = _world()
    order_id = "11111111-1111-4111-8111-111111111111"
    service.save(
        OrderPaymentReminder(
            order_id=order_id,
            payment_method="BAR_VOR_ORT",
            quittung_printed=True,
            paid_on=date(2026, 7, 15),
            cash_received=True,
        ),
        actor_reference="Alice",
    )

    corrected = service.correct_payment_completion(
        order_id,
        correction_id="dddddddd-dddd-4ddd-8ddd-dddddddddddd",
        reason="Barzahlung doch nicht erhalten",
        actor_reference="Bob",
    )

    assert corrected.paid_on is None
    assert corrected.cash_received is False
    assert corrected.quittung_printed is True
    assert corrected.payment_corrections[0].previous_reminder.cash_received is True


def test_payment_completion_correction_rejects_invalid_command_metadata() -> None:
    orders, reminders, _service = _world()
    order_id = "11111111-1111-4111-8111-111111111111"
    service = PaymentReminderService(
        reminders,
        orders,
        now=lambda: _NOW.replace(tzinfo=None),
        today=lambda: date(2026, 7, 15),
    )
    reminders.save(
        OrderPaymentReminder(
            order_id=order_id,
            payment_method="RECHNUNG",
            invoice_created=True,
            invoice_number="RE-META-1",
            sent_on=date(2026, 7, 1),
            paid_on=date(2026, 7, 15),
            paid_recorded_at=_NOW,
            paid_recorded_by="Alice",
            updated_at=_NOW,
        )
    )

    with pytest.raises(ValueError, match="id is required"):
        service.correct_payment_completion(
            order_id,
            correction_id=" ",
            reason="Fehleingabe",
            actor_reference="Bob",
        )
    with pytest.raises(ValueError, match="reason"):
        service.correct_payment_completion(
            order_id,
            correction_id="meta-1",
            reason=" ",
            actor_reference="Bob",
        )
    with pytest.raises(ValueError, match="actor_reference"):
        service.correct_payment_completion(
            order_id,
            correction_id="meta-2",
            reason="Fehleingabe",
            actor_reference=" ",
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        service.correct_payment_completion(
            order_id,
            correction_id="meta-3",
            reason="Fehleingabe",
            actor_reference="Bob",
        )


def test_in_memory_payment_correction_repository_replay_and_conflict() -> None:
    reminders = InMemoryPaymentReminderRepository()
    order_id = "11111111-1111-4111-8111-111111111111"
    previous = OrderPaymentReminder(
        order_id=order_id,
        payment_method="RECHNUNG",
        invoice_created=True,
        invoice_number="RE-MEM-1",
        sent_on=date(2026, 7, 1),
        paid_on=date(2026, 7, 15),
        paid_recorded_at=_NOW,
        paid_recorded_by="Alice",
        updated_at=_NOW,
    )
    current = replace(
        previous,
        paid_on=None,
        paid_recorded_at=None,
        paid_recorded_by=None,
    )
    correction = PaymentCompletionCorrection(
        correction_id="mem-correction-1",
        order_id=order_id,
        reason="Fehleingabe",
        actor_reference="Bob",
        corrected_at=_NOW,
        previous_reminder=previous,
    )

    reminders.save_payment_correction(current, correction)
    reminders.save_payment_correction(current, correction)

    assert reminders.get(order_id) == current
    assert reminders.list_payment_corrections(order_id) == (correction,)

    conflicting = replace(correction, reason="Anderer Grund")
    with pytest.raises(ValueError, match="id conflict"):
        reminders.save_payment_correction(current, conflicting)


def test_invoice_recorded_before_order_revision_requires_correction() -> None:
    orders, reminders, _service = _world()
    order_id = "11111111-1111-4111-8111-111111111111"
    invoice_at = datetime(2026, 7, 15, 9, 0, tzinfo=UTC)
    service = PaymentReminderService(
        reminders,
        orders,
        now=lambda: invoice_at,
        today=lambda: date(2026, 7, 16),
    )
    service.save(
        OrderPaymentReminder(
            order_id=order_id,
            payment_method="RECHNUNG",
            invoice_created=True,
            invoice_number="RE-CORR-1",
            sent_on=date(2026, 7, 15),
        ),
        actor_reference="Alice",
    )
    revision = _append_revision(
        orders,
        created_at=datetime(2026, 7, 16, 10, 0, tzinfo=UTC),
    )

    view = service.view(order_id)

    assert view.next_step == "Rechnungskorrektur erforderlich"
    assert view.next_step_due_on == revision.created_at.date()
    assert view.invoice_number == "RE-CORR-1"

    current = orders.get_order(order_id)
    assert current is not None
    orders.update_order(
        replace(
            current,
            effective_order_version_id=revision.order_version_id,
            candidate_order_version_id=None,
            updated_at=revision.created_at,
        )
    )
    assert service.view(order_id).next_step == "Rechnungskorrektur erforderlich"


def test_quittung_recorded_before_order_revision_requires_reprint() -> None:
    orders, reminders, _service = _world()
    order_id = "11111111-1111-4111-8111-111111111111"
    printed_at = datetime(2026, 7, 15, 9, 0, tzinfo=UTC)
    service = PaymentReminderService(
        reminders,
        orders,
        now=lambda: printed_at,
        today=lambda: date(2026, 7, 16),
    )
    service.save(
        OrderPaymentReminder(
            order_id=order_id,
            payment_method="BAR_VOR_ORT",
            quittung_printed=True,
        ),
        actor_reference="Alice",
    )
    revision = _append_revision(
        orders,
        created_at=datetime(2026, 7, 16, 10, 0, tzinfo=UTC),
    )

    view = service.view(order_id)

    assert view.next_step == "Quittung neu erstellen und drucken"
    assert view.next_step_due_on == revision.created_at.date()
    assert view.quittung_printed is True


def test_paid_order_revision_requires_payment_review_without_difference() -> None:
    orders, reminders, _service = _world()
    order_id = "11111111-1111-4111-8111-111111111111"
    paid_at = datetime(2026, 7, 15, 9, 0, tzinfo=UTC)
    service = PaymentReminderService(
        reminders,
        orders,
        now=lambda: paid_at,
        today=lambda: date(2026, 7, 16),
    )
    service.save(
        OrderPaymentReminder(
            order_id=order_id,
            payment_method="RECHNUNG",
            invoice_created=True,
            invoice_number="RE-PAID-CORR-1",
            sent_on=date(2026, 7, 10),
            paid_on=date(2026, 7, 15),
        ),
        actor_reference="Alice",
    )
    revision = _append_revision(
        orders,
        created_at=datetime(2026, 7, 16, 10, 0, tzinfo=UTC),
    )

    view = service.view(order_id)

    assert view.next_step == "Zahlung nach Auftragsänderung prüfen"
    assert view.next_step_due_on == revision.created_at.date()
    assert view.payment_state_label == "Bezahlt"


def test_legacy_document_without_audit_does_not_guess_revision_ordering() -> None:
    orders, reminders, service = _world()
    order_id = "11111111-1111-4111-8111-111111111111"
    reminders.save(
        OrderPaymentReminder(
            order_id=order_id,
            payment_method="RECHNUNG",
            invoice_created=True,
            invoice_number="RE-LEGACY",
            sent_on=date(2026, 7, 15),
            updated_at=_NOW,
        )
    )
    _append_revision(
        orders,
        created_at=datetime(2026, 7, 16, 10, 0, tzinfo=UTC),
    )

    view = service.view(order_id)

    assert view.next_step != "Rechnungskorrektur erforderlich"


def test_cancelled_unpaid_payment_tasks_are_derived_as_entfallen() -> None:
    orders, reminders, service = _world()
    order_id = "11111111-1111-4111-8111-111111111111"
    service.save(OrderPaymentReminder(order_id=order_id, payment_method="VORKASSE"))
    current = orders.get_order(order_id)
    assert current is not None
    cancelled_at = datetime(2026, 7, 16, 11, 0, tzinfo=UTC)
    orders.update_order(
        replace(current, cancelled_at=cancelled_at, updated_at=cancelled_at)
    )

    view = service.view(order_id)

    assert view.payment_state_label == "Entfallen · Auftrag storniert"
    assert view.next_step is None
    assert view.next_step_due_on is None


def test_cancelled_paid_order_requires_refund_review() -> None:
    orders, reminders, _service = _world()
    order_id = "11111111-1111-4111-8111-111111111111"
    paid_at = datetime(2026, 7, 15, 9, 0, tzinfo=UTC)
    service = PaymentReminderService(
        reminders,
        orders,
        now=lambda: paid_at,
        today=lambda: date(2026, 7, 16),
    )
    service.save(
        OrderPaymentReminder(
            order_id=order_id,
            payment_method="RECHNUNG",
            invoice_created=True,
            invoice_number="RE-REFUND-1",
            sent_on=date(2026, 7, 10),
            paid_on=date(2026, 7, 15),
        ),
        actor_reference="Alice",
    )
    current = orders.get_order(order_id)
    assert current is not None
    cancelled_at = datetime(2026, 7, 16, 11, 0, tzinfo=UTC)
    orders.update_order(
        replace(current, cancelled_at=cancelled_at, updated_at=cancelled_at)
    )

    view = service.view(order_id)

    assert view.payment_state_label == "Bezahlt · Auftrag storniert"
    assert view.next_step == "Rückzahlung prüfen"
    assert view.next_step_due_on == date(2026, 7, 16)
    assert view.paid_on == date(2026, 7, 15)


def test_cancelled_order_cannot_update_reminder() -> None:
    orders, _reminders, service = _world()
    order = orders.get_order("11111111-1111-4111-8111-111111111111")
    assert order is not None
    orders.update_order(replace(order, cancelled_at=_NOW))

    with pytest.raises(ValueError, match="cancelled"):
        service.save(
            OrderPaymentReminder(order_id=order.order_id, payment_method="VORKASSE")
        )
