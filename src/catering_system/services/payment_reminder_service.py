"""Application service for manual office payment reminders."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import Callable
from zoneinfo import ZoneInfo

from catering_system.domain.order_payment_reminder import (
    OrderPaymentReminder,
    PaymentReminderView,
    derive_payment_reminder,
    has_downstream_payment_facts,
    validate_payment_method,
    validate_payment_reminder,
)
from catering_system.repositories.order_repository import OrderRepository
from catering_system.repositories.payment_reminder_repository import (
    PaymentReminderRepository,
)

_BERLIN = ZoneInfo("Europe/Berlin")


class PaymentReminderService:
    def __init__(
        self,
        reminders: PaymentReminderRepository,
        orders: OrderRepository,
        *,
        now: Callable[[], datetime] | None = None,
        today: Callable[[], date] | None = None,
    ) -> None:
        self._reminders = reminders
        self._orders = orders
        self._now = now or (lambda: datetime.now(UTC))
        self._today = today or date.today

    def _event_date(self, order_id: str) -> date:
        order = self._orders.get_order(order_id)
        if order is None:
            raise KeyError(order_id)
        versions = self._orders.list_order_versions(order_id)
        version = next(
            (
                item
                for item in versions
                if item.order_version_id == order.candidate_order_version_id
            ),
            max(versions, key=lambda item: item.version_number, default=None),
        )
        if version is None:
            raise ValueError("order has no event date")
        return version.event_date

    def view(self, order_id: str) -> PaymentReminderView:
        event_date = self._event_date(order_id)
        view = derive_payment_reminder(
            self._reminders.get(order_id),
            event_date=event_date,
            today=self._today(),
        )
        return replace(view, order_id=order_id)

    @staticmethod
    def _actor(value: str) -> str:
        actor = value.strip()
        if not actor or len(actor) > 200:
            raise ValueError("actor_reference must be non-empty and at most 200 chars")
        return actor

    @staticmethod
    def _local_date(value: datetime) -> date:
        return value.astimezone(_BERLIN).date()

    @staticmethod
    def _reject_silent_fact_rewrite(
        current: OrderPaymentReminder,
        incoming: OrderPaymentReminder,
    ) -> None:
        if current.invoice_created and not incoming.invoice_created:
            raise ValueError("invoice creation cannot be cleared silently")
        if (
            current.invoice_number is not None
            and incoming.invoice_number != current.invoice_number
        ):
            raise ValueError("invoice number cannot be changed silently")
        if current.sent_on is not None and incoming.sent_on != current.sent_on:
            raise ValueError("invoice sent date cannot be changed silently")
        if current.paid_on is not None and incoming.paid_on != current.paid_on:
            raise ValueError("payment completion cannot be changed silently")
        if current.cash_received and not incoming.cash_received:
            raise ValueError("cash receipt cannot be cleared silently")
        if current.quittung_printed and not incoming.quittung_printed:
            raise ValueError("Quittung readiness cannot be cleared silently")

    def save(
        self,
        reminder: OrderPaymentReminder,
        *,
        actor_reference: str = "office-panel",
        mark_payment_reminder_sent: bool = False,
        mark_mahnung_sent: bool = False,
    ) -> PaymentReminderView:
        order = self._orders.get_order(reminder.order_id)
        if order is None:
            raise KeyError(reminder.order_id)
        if order.cancelled_at is not None:
            raise ValueError("cancelled order cannot update payment reminders")

        # Deadlines and audit stamps are Core truth. Older clients may still
        # submit due_on; callers are never allowed to forge actor/time evidence.
        reminder = replace(
            reminder,
            due_on=None,
            invoice_created_at=None,
            invoice_created_by=None,
            invoice_sent_recorded_at=None,
            invoice_sent_recorded_by=None,
            payment_reminder_sent_at=None,
            payment_reminder_sent_by=None,
            mahnung_sent_at=None,
            mahnung_sent_by=None,
            quittung_printed_at=None,
            quittung_printed_by=None,
            paid_recorded_at=None,
            paid_recorded_by=None,
        )
        current = self._reminders.get(reminder.order_id)
        if current is not None:
            if (
                current.payment_method != reminder.payment_method
                and has_downstream_payment_facts(current)
            ):
                raise ValueError("payment method cannot change after payment facts")
            self._reject_silent_fact_rewrite(current, reminder)
            reminder = replace(
                reminder,
                invoice_created_at=current.invoice_created_at,
                invoice_created_by=current.invoice_created_by,
                invoice_sent_recorded_at=current.invoice_sent_recorded_at,
                invoice_sent_recorded_by=current.invoice_sent_recorded_by,
                payment_reminder_sent_at=current.payment_reminder_sent_at,
                payment_reminder_sent_by=current.payment_reminder_sent_by,
                mahnung_sent_at=current.mahnung_sent_at,
                mahnung_sent_by=current.mahnung_sent_by,
                quittung_printed_at=current.quittung_printed_at,
                quittung_printed_by=current.quittung_printed_by,
                paid_recorded_at=current.paid_recorded_at,
                paid_recorded_by=current.paid_recorded_by,
            )

        actor = self._actor(actor_reference)
        now = self._now()
        if now.utcoffset() is None:
            raise ValueError("audit clock must return timezone-aware datetime")

        was_invoice_created = current.invoice_created if current is not None else False
        was_sent = current.sent_on if current is not None else None
        was_paid = current.paid_on if current is not None else None
        was_quittung = current.quittung_printed if current is not None else False

        if reminder.invoice_created and not was_invoice_created:
            reminder = replace(
                reminder,
                invoice_created_at=now,
                invoice_created_by=actor,
            )
        if reminder.sent_on is not None and was_sent is None:
            reminder = replace(
                reminder,
                invoice_sent_recorded_at=now,
                invoice_sent_recorded_by=actor,
            )
        if reminder.paid_on is not None and was_paid is None:
            reminder = replace(
                reminder,
                paid_recorded_at=now,
                paid_recorded_by=actor,
            )
        if reminder.quittung_printed and not was_quittung:
            reminder = replace(
                reminder,
                quittung_printed_at=now,
                quittung_printed_by=actor,
            )

        event_date = self._event_date(reminder.order_id)
        today = self._today()
        if mark_payment_reminder_sent and reminder.payment_reminder_sent_at is None:
            if (
                reminder.payment_method == "BAR_VOR_ORT"
                or not reminder.invoice_created
                or reminder.sent_on is None
                or reminder.paid_on is not None
            ):
                raise ValueError("payment reminder cannot be recorded in current state")
            reminder_due = (
                event_date - timedelta(days=6)
                if reminder.payment_method == "VORKASSE"
                else reminder.sent_on + timedelta(days=15)
            )
            if today < reminder_due:
                raise ValueError("payment reminder is not due yet")
            reminder = replace(
                reminder,
                payment_reminder_sent_at=now,
                payment_reminder_sent_by=actor,
            )

        if mark_mahnung_sent and reminder.mahnung_sent_at is None:
            if (
                reminder.payment_method != "RECHNUNG"
                or reminder.paid_on is not None
                or reminder.payment_reminder_sent_at is None
            ):
                raise ValueError("Mahnung cannot be recorded in current state")
            mahnung_due = self._local_date(
                reminder.payment_reminder_sent_at
            ) + timedelta(days=7)
            if today < mahnung_due:
                raise ValueError("Mahnung is not due yet")
            reminder = replace(
                reminder,
                mahnung_sent_at=now,
                mahnung_sent_by=actor,
            )

        validate_payment_reminder(reminder)
        comparable = replace(
            reminder,
            updated_at=current.updated_at if current else None,
        )
        if current is not None and comparable == current:
            return self.view(reminder.order_id)
        self._reminders.save(replace(reminder, updated_at=now))
        return self.view(reminder.order_id)

    def seed_from_conversion(self, order_id: str, payment_method: str) -> None:
        """Persist the explicit conversion choice, with conflict-safe replay."""
        method = validate_payment_method(payment_method)
        current = self._reminders.get(order_id)
        if current is not None:
            if current.payment_method != method:
                raise ValueError(
                    "payment method conflicts with existing conversion selection"
                )
            return
        reminder = OrderPaymentReminder(order_id=order_id, payment_method=method)
        validate_payment_reminder(reminder)
        self._reminders.save(replace(reminder, updated_at=self._now()))
