"""Stdlib-only validators for frozen Core/Courier cash contract V1."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

CONTRACT_VERSION = "courier-cash-handoff-v1"
EVENT_TYPES = frozenset(
    {
        "BAR_RECEIVED_AND_QUITTUNG_HANDED_TO_CUSTOMER",
        "BAR_NOT_RECEIVED",
        "BAR_HANDED_TO_CHEF",
        "BAR_RECEIVED_FROM_DRIVER_BY_CHEF",
        "BAR_RECEIVED_DIRECT_BY_CHEF_AND_QUITTUNG_HANDED_TO_CUSTOMER",
        "BAR_HANDOFF_CORRECTION",
    }
)
NOT_RECEIVED_REASONS = frozenset(
    {
        "CUSTOMER_NOT_FOUND",
        "CUSTOMER_COULD_NOT_PAY",
        "AMOUNT_NOT_ACCEPTABLE",
        "OTHER",
    }
)
ACTOR_ROLES = frozenset({"DRIVER", "CHEF", "OFFICE"})
PROJECTION_KEYS = frozenset(
    {
        "contract_version",
        "bar_required",
        "quittung_status",
        "order_version_id",
        "cash_execution_context_id",
    }
)
COMMAND_KEYS = frozenset(
    {
        "contract_version",
        "idempotency_key",
        "event_type",
        "order_id",
        "assignment_id",
        "order_version_id",
        "cash_execution_context_id",
        "actor_id",
        "actor_role",
        "occurred_at",
        "not_received_reason",
        "note",
        "correction_reason",
        "correction_of_idempotency_key",
    }
)
SUCCESS_KEYS = frozenset(
    {
        "contract_version",
        "event_id",
        "idempotency_key",
        "order_id",
        "cash_state",
        "recorded_at",
    }
)
CASH_STATES = frozenset(
    {
        "READY_FOR_CUSTOMER_HANDOFF",
        "DRIVER_CUSTODY",
        "AWAITING_CHEF_CONFIRMATION",
        "FINAL_PAID",
        "NOT_RECEIVED",
        "MANUAL_REVIEW_REQUIRED",
    }
)
ERRORS = frozenset(
    {
        "unauthorized",
        "invalid_request",
        "unsupported_contract_version",
        "idempotency_conflict",
        "stale_order_revision",
        "stale_cash_context",
        "invalid_transition",
        "core_unavailable",
    }
)
_EVENT_ROLES = {
    "BAR_RECEIVED_AND_QUITTUNG_HANDED_TO_CUSTOMER": frozenset({"DRIVER"}),
    "BAR_NOT_RECEIVED": frozenset({"DRIVER", "CHEF"}),
    "BAR_HANDED_TO_CHEF": frozenset({"DRIVER"}),
    "BAR_RECEIVED_FROM_DRIVER_BY_CHEF": frozenset({"CHEF"}),
    "BAR_RECEIVED_DIRECT_BY_CHEF_AND_QUITTUNG_HANDED_TO_CUSTOMER": frozenset({"CHEF"}),
    "BAR_HANDOFF_CORRECTION": frozenset({"CHEF", "OFFICE"}),
}


def _uuid(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be UUID string")
    try:
        parsed = UUID(value)
    except ValueError as exc:
        raise ValueError(f"{field} must be UUID string") from exc
    if str(parsed) != value.lower():
        raise ValueError(f"{field} must be canonical UUID")
    return value


def _nonblank(value: object, field: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be string")
    if value != value.strip() or not value or len(value) > maximum:
        raise ValueError(f"{field} must be trimmed non-empty string")
    return value


def _datetime(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be date-time string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be date-time string") from exc
    if parsed.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return parsed


def validate_projection(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != PROJECTION_KEYS:
        raise ValueError("invalid cash_handoff projection field set")
    if value["contract_version"] != CONTRACT_VERSION:
        raise ValueError("unsupported contract version")
    if value["bar_required"] is not True:
        raise ValueError("cash_handoff object must require BAR")
    if value["quittung_status"] not in {"PRINTED_CURRENT", "NOT_READY"}:
        raise ValueError("invalid Quittung status")
    _uuid(value["order_version_id"], "order_version_id")
    _uuid(value["cash_execution_context_id"], "cash_execution_context_id")
    return value


def validate_command(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != COMMAND_KEYS:
        raise ValueError("invalid cash command field set")
    if value["contract_version"] != CONTRACT_VERSION:
        raise ValueError("unsupported contract version")
    for field in (
        "idempotency_key",
        "order_id",
        "assignment_id",
        "order_version_id",
        "cash_execution_context_id",
    ):
        _uuid(value[field], field)
    event_type = value["event_type"]
    if event_type not in EVENT_TYPES:
        raise ValueError("invalid event type")
    role = value["actor_role"]
    if role not in ACTOR_ROLES or role not in _EVENT_ROLES[event_type]:
        raise ValueError("actor role not allowed for event")
    _nonblank(value["actor_id"], "actor_id", 200)
    _datetime(value["occurred_at"], "occurred_at")

    reason = value["not_received_reason"]
    note = value["note"]
    correction_reason = value["correction_reason"]
    correction_of = value["correction_of_idempotency_key"]

    if event_type == "BAR_NOT_RECEIVED":
        if reason not in NOT_RECEIVED_REASONS:
            raise ValueError("BAR_NOT_RECEIVED requires reason")
        if reason == "OTHER":
            _nonblank(note, "note", 500)
        elif note is not None:
            raise ValueError("note is only allowed for OTHER")
        if correction_reason is not None or correction_of is not None:
            raise ValueError("not-received command cannot be a correction")
    elif event_type == "BAR_HANDOFF_CORRECTION":
        if reason is not None or note is not None:
            raise ValueError("correction cannot carry not-received fields")
        _nonblank(correction_reason, "correction_reason", 500)
        _uuid(correction_of, "correction_of_idempotency_key")
    else:
        if any(
            item is not None
            for item in (reason, note, correction_reason, correction_of)
        ):
            raise ValueError("event carries fields that must be null")
    return value


def validate_response(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("response must be object")
    if set(value) == {"error"}:
        if value["error"] not in ERRORS:
            raise ValueError("unknown error")
        return value
    if set(value) != SUCCESS_KEYS:
        raise ValueError("invalid success response field set")
    if value["contract_version"] != CONTRACT_VERSION:
        raise ValueError("unsupported contract version")
    for field in ("event_id", "idempotency_key", "order_id"):
        _uuid(value[field], field)
    if value["cash_state"] not in CASH_STATES:
        raise ValueError("invalid cash state")
    _datetime(value["recorded_at"], "recorded_at")
    return value


def assert_no_financial_fields(value: Any) -> None:
    forbidden = ("amount", "cents", "price", "total", "balance", "ledger", "billing")
    if isinstance(value, dict):
        for key, child in value.items():
            lowered = key.lower()
            if any(fragment in lowered for fragment in forbidden):
                raise AssertionError(f"forbidden financial field: {key}")
            assert_no_financial_fields(child)
    elif isinstance(value, list):
        for child in value:
            assert_no_financial_fields(child)
