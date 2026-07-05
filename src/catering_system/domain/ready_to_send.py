"""READY_TO_SEND derived read — OPERATIONAL_CORE_EXECUTION_PACK_V1 §10.

This layer owns its gate rule and reason vocabulary directly. It is deliberately
NOT the B7–B27 progression-blocked vocabulary (progression_blockers.py), which
answers an earlier-stage question; the two must not be merged (pack §10).
READY_TO_SEND is derived on read, never stored (pack §7).
"""

from __future__ import annotations

from dataclasses import dataclass

from catering_system.domain.order import Order, OrderVersion

# Reason vocabulary owned by the operational core gate only.
READY_REASON_ORDER_NOT_FOUND = "ready_to_send_order_not_found"
READY_REASON_ORDER_CANCELLED = "order_cancelled"
READY_REASON_NO_EFFECTIVE_VERSION = "no_effective_version"
READY_REASON_EFFECTIVE_VERSION_NOT_RESOLVABLE = "effective_version_not_resolvable"
READY_REASON_KITCHEN_PRINT_NOT_CONFIRMED = "kitchen_print_not_confirmed"


@dataclass(frozen=True)
class ReadyToSendEvaluation:
    """Blocked-by-default release gate result; derived from Order/OrderVersion facts only."""

    order_id: str
    ready: bool
    reasons: tuple[str, ...]


def evaluate_ready_to_send_from_facts(
    order: Order | None,
    effective_version: OrderVersion | None,
) -> ReadyToSendEvaluation:
    """Pack §10 gate rule: ready only when an effective version exists and its kitchen print is confirmed.

    `effective_version` is the caller-resolved row for order.effective_order_version_id
    (None when unset or not resolvable).
    """
    if order is None:
        return ReadyToSendEvaluation(
            order_id="", ready=False, reasons=(READY_REASON_ORDER_NOT_FOUND,)
        )
    if order.cancelled_at is not None:
        return ReadyToSendEvaluation(
            order_id=order.order_id,
            ready=False,
            reasons=(READY_REASON_ORDER_CANCELLED,),
        )
    if order.effective_order_version_id is None:
        return ReadyToSendEvaluation(
            order_id=order.order_id,
            ready=False,
            reasons=(READY_REASON_NO_EFFECTIVE_VERSION,),
        )
    if effective_version is None or effective_version.order_id != order.order_id:
        return ReadyToSendEvaluation(
            order_id=order.order_id,
            ready=False,
            reasons=(READY_REASON_EFFECTIVE_VERSION_NOT_RESOLVABLE,),
        )
    if effective_version.kitchen_print_confirmed_at is None:
        return ReadyToSendEvaluation(
            order_id=order.order_id,
            ready=False,
            reasons=(READY_REASON_KITCHEN_PRINT_NOT_CONFIRMED,),
        )
    return ReadyToSendEvaluation(order_id=order.order_id, ready=True, reasons=())
