"""In-memory payment reminder adapter."""

from catering_system.domain.order_payment_reminder import OrderPaymentReminder


class InMemoryPaymentReminderRepository:
    def __init__(self) -> None:
        self._rows: dict[str, OrderPaymentReminder] = {}

    def get(self, order_id: str) -> OrderPaymentReminder | None:
        return self._rows.get(order_id)

    def save(self, reminder: OrderPaymentReminder) -> None:
        self._rows[reminder.order_id] = reminder
