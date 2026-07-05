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

from catering_system.domain.operational_core_events import (
    KitchenPrintConfirmed,
    OrderCancelled,
    OrderReadyToSend,
    OrderReadyToSendBlocked,
    OrderVersionMadeEffective,
)
from catering_system.domain.order import Order, OrderVersion
from catering_system.domain.ready_to_send import (
    ReadyToSendEvaluation,
    evaluate_ready_to_send_from_facts,
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
        event_sink: Callable[[object], None] | None = None,
    ) -> None:
        self._order_repository = order_repository
        self._event_sink = event_sink

    def _emit(self, event: object) -> None:
        if self._event_sink is not None:
            self._event_sink(event)

    def _owned_version(self, order_id: str, order_version_id: str) -> OrderVersion:
        order = self._order_repository.get_order(order_id)
        if order is None:
            raise ValueError(f"no order with id {order_id!r}")
        if order.cancelled_at is not None:
            raise ValueError(f"order {order_id!r} is cancelled (Storno); operational commands refused")
        ver = self._order_repository.get_order_version(order_version_id)
        if ver is None or ver.order_id != order_id:
            raise ValueError(
                f"order_version_id {order_version_id!r} is not a version of order {order_id!r}"
            )
        return ver

    def confirm_kitchen_print(self, order_id: str, order_version_id: str) -> OrderVersion:
        """ConfirmKitchenPrint (pack §8.4): ownership-checked, idempotent, not revocable.

        Does not imply an effective switch and does not touch the candidate version.
        """
        ver = self._owned_version(order_id, order_version_id)
        if ver.kitchen_print_confirmed_at is not None:
            return ver
        confirmed = replace(ver, kitchen_print_confirmed_at=_utc_now())
        self._order_repository.save_order_version(confirmed)
        _log.info(
            "confirm_kitchen_print order_id=%s order_version_id=%s", order_id, order_version_id
        )
        self._emit(KitchenPrintConfirmed(order_id=order_id, order_version_id=order_version_id))
        return confirmed

    def make_order_version_effective(self, order_id: str, order_version_id: str) -> Order:
        """MakeOrderVersionEffective (pack §9): gated on confirmed kitchen print.

        May target any owned version that satisfies the gate, not only the candidate.
        Never implicitly changes candidate_order_version_id; history stays immutable.
        """
        ver = self._owned_version(order_id, order_version_id)
        if ver.kitchen_print_confirmed_at is None:
            raise ValueError(
                "effective switch blocked: kitchen print not confirmed "
                f"(order_id={order_id!r}, order_version_id={order_version_id!r})"
            )
        current = self._order_repository.get_order(order_id)
        assert current is not None  # _owned_version already checked existence
        updated = replace(
            current, effective_order_version_id=order_version_id, updated_at=_utc_now()
        )
        self._order_repository.update_order(updated)
        _log.info(
            "make_order_version_effective order_id=%s order_version_id=%s",
            order_id,
            order_version_id,
        )
        self._emit(
            OrderVersionMadeEffective(order_id=order_id, order_version_id=order_version_id)
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
            ev = ReadyToSendEvaluation(order_id=order_id, ready=False, reasons=ev.reasons)
        return ev

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
