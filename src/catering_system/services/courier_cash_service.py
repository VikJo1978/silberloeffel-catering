"""Transactional state machine for Courier BAR execution events."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

from catering_system.domain.courier_cash_handoff import (
    EVENT_CHEF_DIRECT,
    EVENT_CHEF_RECEIVED_FROM_DRIVER,
    EVENT_CORRECTION,
    EVENT_DRIVER_HANDED_TO_CHEF,
    EVENT_DRIVER_RECEIVED,
    EVENT_NOT_RECEIVED,
    QUITTUNG_PRINTED_CURRENT,
    STATE_AWAITING_CHEF,
    STATE_DRIVER_CUSTODY,
    STATE_FINAL_PAID,
    STATE_MANUAL_REVIEW,
    STATE_NOT_RECEIVED,
    STATE_READY,
    CourierCashCommand,
    CourierCashResult,
    CourierCashStoredEvent,
)
from catering_system.repositories.courier_cash_repository import CourierCashRepository
from catering_system.repositories.inquiry_repository import InquiryRepository
from catering_system.repositories.order_repository import OrderRepository
from catering_system.repositories.payment_reminder_repository import (
    PaymentReminderRepository,
)
from catering_system.services.courier_cash_context_service import (
    CourierCashContextService,
)
from catering_system.services.payment_reminder_service import PaymentReminderService

_BERLIN = ZoneInfo("Europe/Berlin")
_TRANSITIONS: dict[tuple[str, str], str] = {
    (STATE_READY, EVENT_DRIVER_RECEIVED): STATE_DRIVER_CUSTODY,
    (STATE_READY, EVENT_NOT_RECEIVED): STATE_NOT_RECEIVED,
    (STATE_DRIVER_CUSTODY, EVENT_DRIVER_HANDED_TO_CHEF): STATE_AWAITING_CHEF,
    (STATE_AWAITING_CHEF, EVENT_CHEF_RECEIVED_FROM_DRIVER): STATE_FINAL_PAID,
    (STATE_READY, EVENT_CHEF_DIRECT): STATE_FINAL_PAID,
}
_CORRECTABLE_STATES = {
    STATE_DRIVER_CUSTODY,
    STATE_AWAITING_CHEF,
    STATE_FINAL_PAID,
    STATE_NOT_RECEIVED,
}


class CourierCashCommandError(Exception):
    def __init__(self, code: str, status: int) -> None:
        self.code = code
        self.status = status
        super().__init__(code)


class CourierCashService:
    def __init__(
        self,
        orders: OrderRepository,
        inquiries: InquiryRepository,
        payments: PaymentReminderRepository,
        cash_events: CourierCashRepository,
        payment_service: PaymentReminderService,
        context_service: CourierCashContextService,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._orders = orders
        self._inquiries = inquiries
        self._payments = payments
        self._cash_events = cash_events
        self._payment_service = payment_service
        self._context_service = context_service
        self._now = now or (lambda: datetime.now(UTC))

    def process(self, command: CourierCashCommand) -> CourierCashResult:
        request_json = json.dumps(
            command.to_json(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        fingerprint = hashlib.sha256(request_json.encode("utf-8")).hexdigest()
        replay = self._cash_events.get_by_idempotency_key(command.idempotency_key)
        if replay is not None:
            if replay.request_fingerprint != fingerprint:
                raise CourierCashCommandError("idempotency_conflict", 409)
            return replay.result()

        order = self._orders.get_order(command.order_id)
        if order is None or order.cancelled_at is not None:
            raise CourierCashCommandError("invalid_transition", 409)
        if order.effective_order_version_id != command.order_version_id:
            raise CourierCashCommandError("stale_order_revision", 409)
        if command.event_type == EVENT_CHEF_DIRECT:
            inquiry = self._inquiries.get_by_id(order.source_inquiry_id)
            if inquiry is None or inquiry.fulfillment_mode != "PICKUP":
                raise CourierCashCommandError("invalid_transition", 409)

        projection = self._context_service.projection(command.order_id)
        if projection is None:
            raise CourierCashCommandError("stale_cash_context", 409)
        if projection.cash_execution_context_id != command.cash_execution_context_id:
            raise CourierCashCommandError("stale_cash_context", 409)

        latest = self._cash_events.get_latest_for_context(
            command.order_id, command.cash_execution_context_id
        )
        if latest is not None:
            from_state = latest.to_state
        else:
            latest_for_order = self._cash_events.get_latest_for_order(command.order_id)
            from_state = (
                STATE_MANUAL_REVIEW
                if latest_for_order is not None
                and latest_for_order.to_state == STATE_MANUAL_REVIEW
                else STATE_READY
            )

        if command.event_type == EVENT_CORRECTION:
            if from_state not in _CORRECTABLE_STATES:
                raise CourierCashCommandError("invalid_transition", 409)
            assert command.correction_of_idempotency_key is not None
            corrected = self._cash_events.get_by_idempotency_key(
                command.correction_of_idempotency_key
            )
            if corrected is None or corrected.order_id != command.order_id:
                raise CourierCashCommandError("invalid_transition", 409)
            to_state = STATE_MANUAL_REVIEW
        else:
            next_state = _TRANSITIONS.get((from_state, command.event_type))
            if next_state is None:
                raise CourierCashCommandError("invalid_transition", 409)
            to_state = next_state
            if (
                from_state == STATE_READY
                and projection.quittung_status != QUITTUNG_PRINTED_CURRENT
            ):
                raise CourierCashCommandError("invalid_transition", 409)

        recorded_at = self._aware_now()
        event_id = str(uuid4())
        result = CourierCashResult(
            event_id=event_id,
            idempotency_key=command.idempotency_key,
            order_id=command.order_id,
            cash_state=to_state,
            recorded_at=recorded_at,
        )

        if to_state == STATE_FINAL_PAID:
            self._record_final_payment(command, recorded_at)
        elif command.event_type == EVENT_CORRECTION:
            assert command.correction_of_idempotency_key is not None
            corrected = self._cash_events.get_by_idempotency_key(
                command.correction_of_idempotency_key
            )
            assert corrected is not None
            if corrected.to_state == STATE_FINAL_PAID:
                payment = self._payments.get(command.order_id)
                if payment is None or (
                    payment.paid_on is None and not payment.cash_received
                ):
                    raise CourierCashCommandError("invalid_transition", 409)
                assert command.correction_reason is not None
                self._payment_service.correct_payment_completion(
                    command.order_id,
                    correction_id=command.idempotency_key,
                    reason=command.correction_reason,
                    actor_reference=self._actor(command),
                )

        response_json = json.dumps(
            result.to_json(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        self._cash_events.append_event(
            CourierCashStoredEvent(
                sequence=0,
                event_id=event_id,
                idempotency_key=command.idempotency_key,
                request_fingerprint=fingerprint,
                request_json=request_json,
                response_json=response_json,
                order_id=command.order_id,
                assignment_id=command.assignment_id,
                order_version_id=command.order_version_id,
                cash_execution_context_id=command.cash_execution_context_id,
                event_type=command.event_type,
                actor_id=command.actor_id,
                actor_role=command.actor_role,
                occurred_at=command.occurred_at,
                recorded_at=recorded_at,
                from_state=from_state,
                to_state=to_state,
                not_received_reason=command.not_received_reason,
                note=command.note,
                correction_reason=command.correction_reason,
                correction_of_idempotency_key=command.correction_of_idempotency_key,
            )
        )
        return result

    def _record_final_payment(
        self, command: CourierCashCommand, recorded_at: datetime
    ) -> None:
        payment = self._payments.get(command.order_id)
        if payment is None or payment.payment_method != "BAR_VOR_ORT":
            raise CourierCashCommandError("stale_cash_context", 409)
        if payment.paid_on is not None or payment.cash_received:
            raise CourierCashCommandError("invalid_transition", 409)
        paid_on = recorded_at.astimezone(_BERLIN).date()
        try:
            self._payment_service.save(
                replace(payment, paid_on=paid_on, cash_received=True),
                actor_reference=self._actor(command),
            )
        except (KeyError, ValueError) as exc:
            raise CourierCashCommandError("invalid_transition", 409) from exc

    @staticmethod
    def _actor(command: CourierCashCommand) -> str:
        return f"courier:{command.actor_role.lower()}:{command.actor_id}"

    def _aware_now(self) -> datetime:
        value = self._now()
        if value.utcoffset() is None:
            raise ValueError("courier cash clock must be timezone-aware")
        return value
