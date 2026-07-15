"""Persistence protocol for non-operational order payment reminders."""

from __future__ import annotations

from typing import Protocol

from catering_system.domain.order_payment_reminder import OrderPaymentReminder


class PaymentReminderRepository(Protocol):
    def get(self, order_id: str) -> OrderPaymentReminder | None: ...

    def save(self, reminder: OrderPaymentReminder) -> None: ...
