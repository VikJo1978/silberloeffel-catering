"""Derive the current frozen Courier BAR execution context."""

from __future__ import annotations

from uuid import UUID, uuid5

from catering_system.domain.courier_cash_handoff import (
    QUITTUNG_NOT_READY,
    QUITTUNG_PRINTED_CURRENT,
    CourierCashProjection,
)
from catering_system.repositories.courier_cash_repository import CourierCashRepository
from catering_system.repositories.order_repository import OrderRepository
from catering_system.repositories.payment_reminder_repository import (
    PaymentReminderRepository,
)

_NAMESPACE = UUID("9de1af8d-0c70-44f8-8b06-0f761980dd9a")


class CourierCashContextService:
    def __init__(
        self,
        orders: OrderRepository,
        payments: PaymentReminderRepository,
        cash_events: CourierCashRepository,
    ) -> None:
        self._orders = orders
        self._payments = payments
        self._cash_events = cash_events

    def projection(self, order_id: str) -> CourierCashProjection | None:
        order = self._orders.get_order(order_id)
        if order is None or order.cancelled_at is not None:
            return None
        payment = self._payments.get(order_id)
        if payment is None or payment.payment_method != "BAR_VOR_ORT":
            return None
        version_id = order.effective_order_version_id
        if version_id is None:
            return None
        version = self._orders.get_order_version(version_id)
        if version is None:
            return None

        method_changes = self._payments.list_method_changes(order_id)
        method_generation = method_changes[0].change_id if method_changes else "initial"
        payment_corrections = self._payments.list_payment_corrections(order_id)
        payment_correction_marker = (
            payment_corrections[0].correction_id if payment_corrections else ""
        )
        cash_correction_marker = (
            self._cash_events.get_latest_correction_id(order_id) or ""
        )
        printed_at = payment.quittung_printed_at
        quittung_current = (
            payment.quittung_printed
            and printed_at is not None
            and printed_at >= version.created_at
        )
        quittung_status = (
            QUITTUNG_PRINTED_CURRENT if quittung_current else QUITTUNG_NOT_READY
        )
        print_generation = printed_at.isoformat() if printed_at is not None else "none"
        material = "|".join(
            (
                "courier-cash-handoff-v1",
                order_id,
                method_generation,
                version_id,
                print_generation,
                payment_correction_marker,
                cash_correction_marker,
            )
        )
        context_id = str(uuid5(_NAMESPACE, material))
        return CourierCashProjection(
            order_version_id=version_id,
            cash_execution_context_id=context_id,
            quittung_status=quittung_status,
        )
