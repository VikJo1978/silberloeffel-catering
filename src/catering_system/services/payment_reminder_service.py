"""Application service for manual office payment reminders."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from typing import Callable

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

    def view(self, order_id: str) -> PaymentReminderView:
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
        view = derive_payment_reminder(
            self._reminders.get(order_id),
            event_date=version.event_date,
            today=self._today(),
        )
        return replace(view, order_id=order_id)

    def save(self, reminder: OrderPaymentReminder) -> PaymentReminderView:
        order = self._orders.get_order(reminder.order_id)
        if order is None:
            raise KeyError(reminder.order_id)
        if order.cancelled_at is not None:
            raise ValueError("cancelled order cannot update payment reminders")
        validate_payment_reminder(reminder)
        current = self._reminders.get(reminder.order_id)
        if (
            current is not None
            and current.payment_method != reminder.payment_method
            and has_downstream_payment_facts(current)
        ):
            raise ValueError("payment method cannot change after payment facts")
        comparable = replace(
            reminder, updated_at=current.updated_at if current else None
        )
        if current is not None and comparable == current:
            return self.view(reminder.order_id)
        self._reminders.save(replace(reminder, updated_at=self._now()))
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
