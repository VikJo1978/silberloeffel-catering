"""Operational core service — OPERATIONAL_CORE_EXECUTION_PACK_V1 §6/§8/§9/§10.

Owns the kitchen-print gate, the effective switch, and the READY_TO_SEND gate
directly. Must not consult the B7–B27 derived progression chain (pack §12):
write-side truth does not depend on read-side projections.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timezone
from uuid import uuid4

from catering_system.domain.operational_core_events import (
    KitchenPrintConfirmed,
    OrderCancelled,
    OrderOperationalPaused,
    OrderOperationalResumed,
    OrderReadyToSend,
    OrderReadyToSendBlocked,
    OrderVersionMadeEffective,
)
from catering_system.domain.order import Order, OrderVersion
from catering_system.domain.order_operational_pause import (
    OrderOperationalPauseEvent,
    derive_operational_pause_projection,
    validate_pause_reason_code,
    validate_resume_reason_code,
)
from catering_system.domain.ready_to_send import (
    READY_REASON_OPERATIONAL_PAUSE,
    ReadyToSendEvaluation,
    evaluate_ready_to_send_from_facts,
)
from catering_system.repositories.in_memory_order_operational_pause_repository import (
    InMemoryOrderOperationalPauseRepository,
)
from catering_system.repositories.order_operational_pause_repository import (
    OrderOperationalPauseRepository,
)
from catering_system.repositories.order_repository import OrderRepository

_log = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class OperationalCoreService:
    """ConfirmKitchenPrint, MakeOrderVersionEffective, evaluate/request READY_TO_SEND."""

    def __init__(
        self,
        order_repository: OrderRepository,
        *,
        pause_repository: OrderOperationalPauseRepository | None = None,
        event_sink: Callable[[object], None] | None = None,
    ) -> None:
        self._order_repository = order_repository
        self._pause_repository = (
            pause_repository
            if pause_repository is not None
            else InMemoryOrderOperationalPauseRepository()
        )
        self._event_sink = event_sink

    def _emit(self, event: object) -> None:
        if self._event_sink is not None:
            self._event_sink(event)

    def _owned_version(self, order_id: str, order_version_id: str) -> OrderVersion:
        order = self._order_repository.get_order(order_id)
        if order is None:
            raise ValueError(f"no order with id {order_id!r}")
        if order.cancelled_at is not None:
            raise ValueError(
                f"order {order_id!r} is cancelled (Storno); operational commands refused"
            )
        ver = self._order_repository.get_order_version(order_version_id)
        if ver is None or ver.order_id != order_id:
            raise ValueError(
                f"order_version_id {order_version_id!r} is not a version of order {order_id!r}"
            )
        return ver

    def confirm_kitchen_print(
        self, order_id: str, order_version_id: str
    ) -> OrderVersion:
        """ConfirmKitchenPrint (pack §8.4): ownership-checked, idempotent, not revocable.

        Does not imply an effective switch and does not touch the candidate version.
        """
        ver = self._owned_version(order_id, order_version_id)
        if ver.kitchen_print_confirmed_at is not None:
            return ver
        confirmed = replace(ver, kitchen_print_confirmed_at=_utc_now())
        self._order_repository.update_order_version(confirmed)
        _log.info(
            "confirm_kitchen_print order_id=%s order_version_id=%s",
            order_id,
            order_version_id,
        )
        self._emit(
            KitchenPrintConfirmed(order_id=order_id, order_version_id=order_version_id)
        )
        return confirmed

    def make_order_version_effective(
        self, order_id: str, order_version_id: str
    ) -> Order:
        """Select the initial stand or the exact confirmed current candidate."""
        ver = self._owned_version(order_id, order_version_id)
        current = self._order_repository.get_order(order_id)
        assert current is not None  # _owned_version already checked existence
        if (
            current.effective_order_version_id == order_version_id
            and current.candidate_order_version_id is None
        ):
            return current
        is_initial_selection = (
            current.effective_order_version_id is None
            and current.candidate_order_version_id is None
        )
        if (
            not is_initial_selection
            and current.candidate_order_version_id != order_version_id
        ):
            raise ValueError(
                "effective switch blocked: version is not current candidate "
                f"(order_id={order_id!r}, order_version_id={order_version_id!r})"
            )
        if ver.kitchen_print_confirmed_at is None:
            raise ValueError(
                "effective switch blocked: kitchen print not confirmed "
                f"(order_id={order_id!r}, order_version_id={order_version_id!r})"
            )
        updated = replace(
            current,
            effective_order_version_id=order_version_id,
            candidate_order_version_id=None,
            updated_at=_utc_now(),
        )
        self._order_repository.update_order(updated)
        _log.info(
            "make_order_version_effective order_id=%s order_version_id=%s",
            order_id,
            order_version_id,
        )
        self._emit(
            OrderVersionMadeEffective(
                order_id=order_id, order_version_id=order_version_id
            )
        )
        return updated

    def cancel_order(self, order_id: str) -> Order:
        """CancelOrder (STORNO pack §2): explicit fact, idempotent, not revocable.

        History, candidate, and effective references stay untouched; their meaning
        is neutralized by the derived reads (READY_TO_SEND, Wochenübersicht).
        """
        current = self._order_repository.get_order(order_id)
        if current is None:
            raise ValueError(f"no order with id {order_id!r}")
        if current.cancelled_at is not None:
            return current
        cancelled = replace(current, cancelled_at=_utc_now(), updated_at=_utc_now())
        self._order_repository.update_order(cancelled)
        _log.info("cancel_order order_id=%s", order_id)
        self._emit(OrderCancelled(order_id=order_id))
        return cancelled

    def get_active_operational_pause(
        self, order_id: str
    ) -> OrderOperationalPauseEvent | None:
        """Derived read: active order-level PAUSE, if any."""
        return self._pause_repository.get_active_pause(order_id)

    def get_operational_pause_projection(self, order_id: str) -> dict[str, object]:
        return derive_operational_pause_projection(
            self._pause_repository.list_events(order_id)
        )

    def list_operational_pause_history(
        self, order_id: str
    ) -> tuple[OrderOperationalPauseEvent, ...]:
        return self._pause_repository.list_events(order_id)

    def pause_order(
        self,
        order_id: str,
        *,
        reason_code: str,
        note: str | None,
        actor_reference: str,
        command_id: str,
        expected_latest_pause_event_id: str | None,
    ) -> OrderOperationalPauseEvent:
        """Append one authoritative paused event for an active Order."""
        order = self._order_repository.get_order(order_id)
        if order is None:
            raise ValueError(f"no order with id {order_id!r}")
        if order.cancelled_at is not None:
            raise ValueError(
                f"order {order_id!r} is cancelled (Storno); operational commands refused"
            )
        validate_pause_reason_code(reason_code)
        projection = self.get_operational_pause_projection(order_id)
        if projection["active"]:
            raise ValueError(f"order {order_id!r} is already paused")
        if projection.get("latest_pause_event_id") != expected_latest_pause_event_id:
            raise ValueError("stale operational pause state")
        event = OrderOperationalPauseEvent(
            pause_event_id=str(uuid4()),
            order_id=order_id,
            action="paused",
            reason_code=reason_code,
            note=note,
            actor_reference=actor_reference,
            occurred_at=_utc_now(),
            command_id=command_id,
        )
        self._pause_repository.append_event(event)
        _log.info(
            "pause_order order_id=%s pause_event_id=%s reason_code=%s",
            order_id,
            event.pause_event_id,
            reason_code,
        )
        self._emit(
            OrderOperationalPaused(
                order_id=order_id, pause_event_id=event.pause_event_id
            )
        )
        return event

    def resume_order(
        self,
        order_id: str,
        *,
        reason_code: str,
        note: str | None,
        actor_reference: str,
        command_id: str,
        expected_current_pause_event_id: str,
        expected_latest_pause_event_id: str,
    ) -> OrderOperationalPauseEvent:
        """Append one authoritative resumed event; prior pause history stays intact."""
        order = self._order_repository.get_order(order_id)
        if order is None:
            raise ValueError(f"no order with id {order_id!r}")
        if order.cancelled_at is not None:
            raise ValueError(
                f"order {order_id!r} is cancelled (Storno); operational commands refused"
            )
        validate_resume_reason_code(reason_code)
        projection = self.get_operational_pause_projection(order_id)
        if not projection["active"]:
            raise ValueError(f"order {order_id!r} is not paused")
        if projection.get("current_pause_event_id") != expected_current_pause_event_id:
            raise ValueError("stale operational pause state")
        if projection.get("latest_pause_event_id") != expected_latest_pause_event_id:
            raise ValueError("stale operational pause state")
        active = self._pause_repository.get_active_pause(order_id)
        assert active is not None
        event = OrderOperationalPauseEvent(
            pause_event_id=str(uuid4()),
            order_id=order_id,
            action="resumed",
            reason_code=reason_code,
            note=note,
            actor_reference=actor_reference,
            occurred_at=_utc_now(),
            command_id=command_id,
            resumes_pause_event_id=active.pause_event_id,
        )
        self._pause_repository.append_event(event)
        _log.info(
            "resume_order order_id=%s pause_event_id=%s resumed_pause_event_id=%s",
            order_id,
            event.pause_event_id,
            active.pause_event_id,
        )
        self._emit(
            OrderOperationalResumed(
                order_id=order_id,
                pause_event_id=event.pause_event_id,
                resumed_pause_event_id=active.pause_event_id,
            )
        )
        return event

    def evaluate_ready_to_send(self, order_id: str) -> ReadyToSendEvaluation:
        """Pure read (pack §6.1): computes the §10 gate; mutates nothing, emits nothing."""
        order = self._order_repository.get_order(order_id)
        effective: OrderVersion | None = None
        if order is not None and order.effective_order_version_id is not None:
            effective = self._order_repository.get_order_version(
                order.effective_order_version_id
            )
        ev = evaluate_ready_to_send_from_facts(order, effective)
        if order is None:
            # keep the requested id in the result for unknown orders
            return ReadyToSendEvaluation(
                order_id=order_id, ready=False, reasons=ev.reasons
            )
        if self._pause_repository.get_active_pause(order_id) is None:
            return ev
        reasons = list(ev.reasons)
        if READY_REASON_OPERATIONAL_PAUSE not in reasons:
            reasons.insert(0, READY_REASON_OPERATIONAL_PAUSE)
        return ReadyToSendEvaluation(
            order_id=ev.order_id,
            ready=False,
            reasons=tuple(reasons),
        )

    def request_ready_to_send(self, order_id: str) -> ReadyToSendEvaluation:
        """RequestReadyToSend (pack §6.1): changes no order truth in either branch.

        Only records the attempt/result as an event: OrderReadyToSend on success,
        OrderReadyToSendBlocked (with this layer's reasons) when the gate is unsatisfied.
        """
        ev = self.evaluate_ready_to_send(order_id)
        if ev.ready:
            self._emit(OrderReadyToSend(order_id=order_id))
        else:
            self._emit(OrderReadyToSendBlocked(order_id=order_id, reasons=ev.reasons))
        _log.info("request_ready_to_send order_id=%s ready=%s", order_id, ev.ready)
        return ev
