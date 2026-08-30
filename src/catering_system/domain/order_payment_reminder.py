"""Office payment reminders kept separate from operational order truth."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

PaymentMethod = Literal["VORKASSE", "RECHNUNG", "BAR_VOR_ORT"]
PAYMENT_METHODS: tuple[PaymentMethod, ...] = (
    "VORKASSE",
    "RECHNUNG",
    "BAR_VOR_ORT",
)
PAYMENT_METHOD_LABELS: dict[PaymentMethod, str] = {
    "VORKASSE": "Vorkasse",
    "RECHNUNG": "Rechnung",
    "BAR_VOR_ORT": "Bar vor Ort",
}
_BERLIN = ZoneInfo("Europe/Berlin")


def validate_payment_method(value: str) -> PaymentMethod:
    if value == "VORKASSE":
        return "VORKASSE"
    if value == "RECHNUNG":
        return "RECHNUNG"
    if value == "BAR_VOR_ORT":
        return "BAR_VOR_ORT"
    raise ValueError("invalid payment method")


@dataclass(frozen=True)
class OrderPaymentReminder:
    """Manual office reminder facts; never an accounting document or status."""

    order_id: str
    payment_method: PaymentMethod
    invoice_created: bool = False
    invoice_number: str | None = None
    sent_on: date | None = None
    due_on: date | None = None
    paid_on: date | None = None
    cash_received: bool = False
    quittung_printed: bool = False
    updated_at: datetime | None = None
    invoice_created_at: datetime | None = None
    invoice_created_by: str | None = None
    invoice_sent_recorded_at: datetime | None = None
    invoice_sent_recorded_by: str | None = None
    payment_reminder_sent_at: datetime | None = None
    payment_reminder_sent_by: str | None = None
    mahnung_sent_at: datetime | None = None
    mahnung_sent_by: str | None = None
    quittung_printed_at: datetime | None = None
    quittung_printed_by: str | None = None
    paid_recorded_at: datetime | None = None
    paid_recorded_by: str | None = None


@dataclass(frozen=True)
class PaymentReminderView:
    order_id: str
    payment_method: PaymentMethod | None
    payment_method_label: str
    invoice_created: bool
    invoice_number: str | None
    sent_on: date | None
    due_on: date | None
    paid_on: date | None
    cash_received: bool
    quittung_printed: bool
    invoice_state_label: str | None
    payment_state_label: str
    next_step: str | None
    updated_at: datetime | None
    next_step_due_on: date | None = None
    invoice_created_at: datetime | None = None
    invoice_created_by: str | None = None
    invoice_sent_recorded_at: datetime | None = None
    invoice_sent_recorded_by: str | None = None
    payment_reminder_sent_at: datetime | None = None
    payment_reminder_sent_by: str | None = None
    mahnung_sent_at: datetime | None = None
    mahnung_sent_by: str | None = None
    quittung_printed_at: datetime | None = None
    quittung_printed_by: str | None = None
    paid_recorded_at: datetime | None = None
    paid_recorded_by: str | None = None


def _validate_audit_pair(
    timestamp: datetime | None,
    actor: str | None,
    *,
    name: str,
) -> None:
    if (timestamp is None) != (actor is None):
        raise ValueError(f"{name} audit requires timestamp and actor together")
    if timestamp is not None and timestamp.utcoffset() is None:
        raise ValueError(f"{name} audit timestamp must be timezone-aware")
    if actor is not None and (not actor.strip() or len(actor) > 200):
        raise ValueError(f"{name} audit actor must be non-empty and at most 200 chars")


def validate_payment_reminder(reminder: OrderPaymentReminder) -> None:
    """Reject contradictory manual facts before they reach persistence."""
    if not reminder.order_id:
        raise ValueError("order_id is required")
    validate_payment_method(reminder.payment_method)
    number = reminder.invoice_number
    if number is not None and (not number.strip() or len(number) > 200):
        raise ValueError("invoice number must be non-empty and at most 200 chars")

    audit_pairs = (
        ("invoice created", reminder.invoice_created_at, reminder.invoice_created_by),
        (
            "invoice sent",
            reminder.invoice_sent_recorded_at,
            reminder.invoice_sent_recorded_by,
        ),
        (
            "payment reminder",
            reminder.payment_reminder_sent_at,
            reminder.payment_reminder_sent_by,
        ),
        ("Mahnung", reminder.mahnung_sent_at, reminder.mahnung_sent_by),
        (
            "Quittung printed",
            reminder.quittung_printed_at,
            reminder.quittung_printed_by,
        ),
        ("payment recorded", reminder.paid_recorded_at, reminder.paid_recorded_by),
    )
    for name, timestamp, actor in audit_pairs:
        _validate_audit_pair(timestamp, actor, name=name)

    if reminder.invoice_created_at is not None and not reminder.invoice_created:
        raise ValueError("invoice creation audit requires invoice_created")
    if reminder.invoice_sent_recorded_at is not None and reminder.sent_on is None:
        raise ValueError("invoice sent audit requires sent_on")
    if reminder.paid_recorded_at is not None and reminder.paid_on is None:
        raise ValueError("payment audit requires paid_on")

    if reminder.payment_method == "BAR_VOR_ORT":
        if (
            reminder.invoice_created
            or number is not None
            or reminder.sent_on is not None
            or reminder.due_on is not None
            or reminder.invoice_created_at is not None
            or reminder.invoice_sent_recorded_at is not None
            or reminder.payment_reminder_sent_at is not None
            or reminder.mahnung_sent_at is not None
        ):
            raise ValueError("cash payment cannot carry invoice reminder facts")
        if reminder.cash_received != (reminder.paid_on is not None):
            raise ValueError("cash receipt and paid date must be recorded together")
        if reminder.quittung_printed_at is not None and not reminder.quittung_printed:
            raise ValueError("Quittung audit requires printed readiness")
        return

    if reminder.quittung_printed or reminder.quittung_printed_at is not None:
        raise ValueError("invoice payment cannot carry quittung readiness facts")
    if reminder.cash_received:
        raise ValueError("invoice payment cannot be marked as cash received")
    invoice_facts = (
        number is not None
        or reminder.sent_on is not None
        or reminder.due_on is not None
        or reminder.paid_on is not None
        or reminder.invoice_created_at is not None
        or reminder.invoice_sent_recorded_at is not None
        or reminder.payment_reminder_sent_at is not None
        or reminder.mahnung_sent_at is not None
    )
    if not reminder.invoice_created and invoice_facts:
        raise ValueError("invoice facts require invoice_created")
    if reminder.invoice_created and number is None:
        raise ValueError("invoice number is required after invoice creation")
    if reminder.payment_reminder_sent_at is not None and reminder.sent_on is None:
        raise ValueError("payment reminder audit requires sent invoice")
    if reminder.mahnung_sent_at is not None:
        if reminder.payment_method != "RECHNUNG":
            raise ValueError("Mahnung is only valid for Rechnung")
        if reminder.payment_reminder_sent_at is None:
            raise ValueError("Mahnung requires a recorded payment reminder")


def has_downstream_payment_facts(reminder: OrderPaymentReminder) -> bool:
    return bool(
        reminder.invoice_created
        or reminder.invoice_number
        or reminder.sent_on
        or reminder.due_on
        or reminder.paid_on
        or reminder.cash_received
        or reminder.quittung_printed
        or reminder.invoice_created_at
        or reminder.invoice_sent_recorded_at
        or reminder.payment_reminder_sent_at
        or reminder.mahnung_sent_at
        or reminder.quittung_printed_at
        or reminder.paid_recorded_at
    )


def _local_date(value: datetime) -> date:
    return value.astimezone(_BERLIN).date()


def _view(
    reminder: OrderPaymentReminder,
    *,
    due_on: date | None,
    invoice_state_label: str | None,
    payment_state_label: str,
    next_step: str | None,
    next_step_due_on: date | None,
) -> PaymentReminderView:
    return PaymentReminderView(
        order_id=reminder.order_id,
        payment_method=reminder.payment_method,
        payment_method_label=PAYMENT_METHOD_LABELS[reminder.payment_method],
        invoice_created=reminder.invoice_created,
        invoice_number=reminder.invoice_number,
        sent_on=reminder.sent_on,
        due_on=due_on,
        paid_on=reminder.paid_on,
        cash_received=reminder.cash_received,
        quittung_printed=reminder.quittung_printed,
        invoice_state_label=invoice_state_label,
        payment_state_label=payment_state_label,
        next_step=next_step,
        updated_at=reminder.updated_at,
        next_step_due_on=next_step_due_on,
        invoice_created_at=reminder.invoice_created_at,
        invoice_created_by=reminder.invoice_created_by,
        invoice_sent_recorded_at=reminder.invoice_sent_recorded_at,
        invoice_sent_recorded_by=reminder.invoice_sent_recorded_by,
        payment_reminder_sent_at=reminder.payment_reminder_sent_at,
        payment_reminder_sent_by=reminder.payment_reminder_sent_by,
        mahnung_sent_at=reminder.mahnung_sent_at,
        mahnung_sent_by=reminder.mahnung_sent_by,
        quittung_printed_at=reminder.quittung_printed_at,
        quittung_printed_by=reminder.quittung_printed_by,
        paid_recorded_at=reminder.paid_recorded_at,
        paid_recorded_by=reminder.paid_recorded_by,
    )


def derive_payment_reminder(
    reminder: OrderPaymentReminder | None,
    *,
    event_date: date,
    today: date,
) -> PaymentReminderView:
    """Purely derive German office labels and the next reminder action."""
    if reminder is None:
        return PaymentReminderView(
            order_id="",
            payment_method=None,
            payment_method_label="Noch nicht gewählt",
            invoice_created=False,
            invoice_number=None,
            sent_on=None,
            due_on=None,
            paid_on=None,
            cash_received=False,
            quittung_printed=False,
            invoice_state_label=None,
            payment_state_label="Offen",
            next_step="Zahlungsart auswählen",
            updated_at=None,
        )

    validate_payment_reminder(reminder)
    method = reminder.payment_method
    if method == "BAR_VOR_ORT":
        if not reminder.quittung_printed:
            state, next_step, next_due = (
                "Offen",
                "Quittung vorbereiten/drucken",
                None,
            )
        elif reminder.cash_received:
            state, next_step, next_due = "Bezahlt", None, None
        elif today > event_date:
            state, next_step, next_due = "Offen", "Barzahlung klären", event_date
        else:
            state, next_step, next_due = (
                "Offen",
                "Barzahlung vor Ort abwarten",
                event_date,
            )
        return _view(
            reminder,
            due_on=None,
            invoice_state_label=None,
            payment_state_label=state,
            next_step=next_step,
            next_step_due_on=next_due,
        )

    canonical_due = (
        event_date - timedelta(days=7)
        if method == "VORKASSE"
        else (
            reminder.sent_on + timedelta(days=14)
            if reminder.sent_on is not None
            else None
        )
    )
    invoice_label = "Erstellt" if reminder.invoice_created else "Noch nicht erstellt"
    if not reminder.invoice_created:
        return _view(
            reminder,
            due_on=canonical_due,
            invoice_state_label=invoice_label,
            payment_state_label="Offen",
            next_step=(
                "Rechnung erstellen/senden"
                if method == "VORKASSE"
                else "Rechnung in der Buchhaltung erstellen"
            ),
            next_step_due_on=None,
        )
    if reminder.paid_on is not None:
        return _view(
            reminder,
            due_on=canonical_due,
            invoice_state_label=invoice_label,
            payment_state_label="Bezahlt",
            next_step=None,
            next_step_due_on=None,
        )
    if reminder.sent_on is None or canonical_due is None:
        return _view(
            reminder,
            due_on=canonical_due,
            invoice_state_label=invoice_label,
            payment_state_label="Offen",
            next_step="Rechnungsdaten vervollständigen",
            next_step_due_on=None,
        )

    if canonical_due < today:
        days = (today - canonical_due).days
        duration = "1 Tag" if days == 1 else f"{days} Tagen"
        state = (
            "Sofort fällig"
            if method == "VORKASSE" and today <= event_date
            else f"Überfällig seit {duration}"
        )
    elif canonical_due == today:
        state = "Heute fällig"
    elif method == "RECHNUNG" and (canonical_due - today).days in {7, 3}:
        state = f"Fällig in {(canonical_due - today).days} Tagen"
    else:
        state = "Offen"

    if method == "VORKASSE":
        reminder_due = event_date - timedelta(days=6)
        urgent_due = event_date - timedelta(days=3)
        if today >= urgent_due:
            next_step = "Dringende manuelle Entscheidung erforderlich"
            next_due = urgent_due
        elif today >= reminder_due and reminder.payment_reminder_sent_at is None:
            next_step = "Zahlungserinnerung senden"
            next_due = reminder_due
        elif today >= reminder_due:
            next_step = "Zahlungseingang prüfen"
            next_due = urgent_due
        else:
            next_step = "Zahlungseingang prüfen"
            next_due = canonical_due
        return _view(
            reminder,
            due_on=canonical_due,
            invoice_state_label=invoice_label,
            payment_state_label=state,
            next_step=next_step,
            next_step_due_on=next_due,
        )

    reminder_due = canonical_due + timedelta(days=1)
    if reminder.payment_reminder_sent_at is None:
        next_step = (
            "Zahlungserinnerung senden"
            if today >= reminder_due
            else "Zahlungseingang prüfen"
        )
        next_due = reminder_due if today > canonical_due else canonical_due
    elif reminder.mahnung_sent_at is None:
        mahnung_due = _local_date(reminder.payment_reminder_sent_at) + timedelta(days=7)
        next_step = (
            "Mahnung senden"
            if today >= mahnung_due
            else "Zahlungseingang prüfen"
        )
        next_due = mahnung_due
    else:
        manual_due = _local_date(reminder.mahnung_sent_at) + timedelta(days=7)
        next_step = (
            "Manuelle Entscheidung erforderlich"
            if today >= manual_due
            else "Zahlungseingang prüfen"
        )
        next_due = manual_due

    return _view(
        reminder,
        due_on=canonical_due,
        invoice_state_label=invoice_label,
        payment_state_label=state,
        next_step=next_step,
        next_step_due_on=next_due,
    )
