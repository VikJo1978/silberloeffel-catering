"""In-memory payment reminder adapter."""

from catering_system.domain.order_payment_reminder import (
    OrderPaymentReminder,
    PaymentCompletionCorrection,
    PaymentMethodChange,
)


class InMemoryPaymentReminderRepository:
    def __init__(self) -> None:
        self._rows: dict[str, OrderPaymentReminder] = {}
        self._method_changes: dict[str, list[PaymentMethodChange]] = {}

    def get(self, order_id: str) -> OrderPaymentReminder | None:
        return self._rows.get(order_id)

    def save(self, reminder: OrderPaymentReminder) -> None:
        self._rows[reminder.order_id] = reminder

    def list_method_changes(self, order_id: str) -> tuple[PaymentMethodChange, ...]:
        return tuple(reversed(self._method_changes.get(order_id, [])))

    def save_method_change(
        self,
        reminder: OrderPaymentReminder,
        change: PaymentMethodChange,
    ) -> None:
        self._rows[reminder.order_id] = reminder
        self._method_changes.setdefault(reminder.order_id, []).append(change)
