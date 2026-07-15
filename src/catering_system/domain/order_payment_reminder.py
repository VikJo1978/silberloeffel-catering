"""Office payment reminders kept separate from operational order truth."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

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
    updated_at: datetime | None = None


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
    invoice_state_label: str | None
    payment_state_label: str
    next_step: str | None
    updated_at: datetime | None


def validate_payment_reminder(reminder: OrderPaymentReminder) -> None:
    """Reject contradictory manual facts before they reach persistence."""
    if not reminder.order_id:
        raise ValueError("order_id is required")
    validate_payment_method(reminder.payment_method)
    number = reminder.invoice_number
    if number is not None and (not number.strip() or len(number) > 200):
        raise ValueError("invoice number must be non-empty and at most 200 chars")

    if reminder.payment_method == "BAR_VOR_ORT":
        if (
            reminder.invoice_created
            or number is not None
            or reminder.sent_on is not None
            or reminder.due_on is not None
        ):
            raise ValueError("cash payment cannot carry invoice reminder facts")
        if reminder.cash_received != (reminder.paid_on is not None):
            raise ValueError("cash receipt and paid date must be recorded together")
        return

    if reminder.cash_received:
        raise ValueError("invoice payment cannot be marked as cash received")
    invoice_facts = (
        number is not None
        or reminder.sent_on is not None
        or reminder.due_on is not None
        or reminder.paid_on is not None
    )
    if not reminder.invoice_created and invoice_facts:
        raise ValueError("invoice facts require invoice_created")
    if reminder.invoice_created and number is None:
        raise ValueError("invoice number is required after invoice creation")


def has_downstream_payment_facts(reminder: OrderPaymentReminder) -> bool:
    return bool(
        reminder.invoice_created
        or reminder.invoice_number
        or reminder.sent_on
        or reminder.due_on
        or reminder.paid_on
        or reminder.cash_received
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
            invoice_state_label=None,
            payment_state_label="Offen",
            next_step="Zahlungsart auswählen",
            updated_at=None,
        )

    validate_payment_reminder(reminder)
    method = reminder.payment_method
    if method == "BAR_VOR_ORT":
        if reminder.cash_received:
            state, next_step = "Bezahlt", None
        elif today > event_date:
            state, next_step = "Offen", "Barzahlung bestätigen"
        else:
            state, next_step = "Offen", "Barzahlung vor Ort abwarten"
        return PaymentReminderView(
            order_id=reminder.order_id,
            payment_method=method,
            payment_method_label=PAYMENT_METHOD_LABELS[method],
            invoice_created=False,
            invoice_number=None,
            sent_on=None,
            due_on=None,
            paid_on=reminder.paid_on,
            cash_received=reminder.cash_received,
            invoice_state_label=None,
            payment_state_label=state,
            next_step=next_step,
            updated_at=reminder.updated_at,
        )

    invoice_label = "Erstellt" if reminder.invoice_created else "Noch nicht erstellt"
    if not reminder.invoice_created:
        state = "Offen"
        next_step = (
            "Vorauszahlungsrechnung in der Buchhaltung erstellen"
            if method == "VORKASSE"
            else "Rechnung in der Buchhaltung erstellen"
        )
    elif reminder.paid_on is not None:
        state, next_step = "Bezahlt", None
    elif reminder.sent_on is None or reminder.due_on is None:
        state, next_step = "Offen", "Rechnungsdaten vervollständigen"
    elif reminder.due_on < today:
        days = (today - reminder.due_on).days
        duration = "1 Tag" if days == 1 else f"{days} Tagen"
        state, next_step = f"Überfällig seit {duration}", "Zahlung überfällig"
    else:
        state, next_step = "Offen", "Zahlungseingang prüfen"
    return PaymentReminderView(
        order_id=reminder.order_id,
        payment_method=method,
        payment_method_label=PAYMENT_METHOD_LABELS[method],
        invoice_created=reminder.invoice_created,
        invoice_number=reminder.invoice_number,
        sent_on=reminder.sent_on,
        due_on=reminder.due_on,
        paid_on=reminder.paid_on,
        cash_received=False,
        invoice_state_label=invoice_label,
        payment_state_label=state,
        next_step=next_step,
        updated_at=reminder.updated_at,
    )
