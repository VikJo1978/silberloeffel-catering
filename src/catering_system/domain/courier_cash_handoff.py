"""Frozen COURIER_CASH_HANDOFF_CONTRACT_V1 runtime domain."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

CONTRACT_VERSION = "courier-cash-handoff-v1"
QUITTUNG_PRINTED_CURRENT = "PRINTED_CURRENT"
QUITTUNG_NOT_READY = "NOT_READY"

STATE_READY = "READY_FOR_CUSTOMER_HANDOFF"
STATE_DRIVER_CUSTODY = "DRIVER_CUSTODY"
STATE_AWAITING_CHEF = "AWAITING_CHEF_CONFIRMATION"
STATE_FINAL_PAID = "FINAL_PAID"
STATE_NOT_RECEIVED = "NOT_RECEIVED"
STATE_MANUAL_REVIEW = "MANUAL_REVIEW_REQUIRED"

EVENT_DRIVER_RECEIVED = "BAR_RECEIVED_AND_QUITTUNG_HANDED_TO_CUSTOMER"
EVENT_NOT_RECEIVED = "BAR_NOT_RECEIVED"
EVENT_DRIVER_HANDED_TO_CHEF = "BAR_HANDED_TO_CHEF"
EVENT_CHEF_RECEIVED_FROM_DRIVER = "BAR_RECEIVED_FROM_DRIVER_BY_CHEF"
EVENT_CHEF_DIRECT = "BAR_RECEIVED_DIRECT_BY_CHEF_AND_QUITTUNG_HANDED_TO_CUSTOMER"
EVENT_CORRECTION = "BAR_HANDOFF_CORRECTION"

EVENT_TYPES = frozenset(
    {
        EVENT_DRIVER_RECEIVED,
        EVENT_NOT_RECEIVED,
        EVENT_DRIVER_HANDED_TO_CHEF,
        EVENT_CHEF_RECEIVED_FROM_DRIVER,
        EVENT_CHEF_DIRECT,
        EVENT_CORRECTION,
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
_EVENT_ROLES = {
    EVENT_DRIVER_RECEIVED: frozenset({"DRIVER"}),
    EVENT_NOT_RECEIVED: frozenset({"DRIVER", "CHEF"}),
    EVENT_DRIVER_HANDED_TO_CHEF: frozenset({"DRIVER"}),
    EVENT_CHEF_RECEIVED_FROM_DRIVER: frozenset({"CHEF"}),
    EVENT_CHEF_DIRECT: frozenset({"CHEF"}),
    EVENT_CORRECTION: frozenset({"CHEF", "OFFICE"}),
}
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


def _uuid(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be UUID string")
    try:
        parsed = UUID(value)
    except ValueError as exc:
        raise ValueError(f"{field} must be UUID string") from exc
    if str(parsed) != value:
        raise ValueError(f"{field} must be canonical lowercase UUID")
    return value


def _text(value: object, field: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be string")
    if not value or value != value.strip() or len(value) > maximum:
        raise ValueError(f"{field} must be trimmed non-empty text")
    return value


def _optional_text(value: object, field: str, maximum: int) -> str | None:
    if value is None:
        return None
    return _text(value, field, maximum)


def _date_time(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be date-time string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be date-time string") from exc
    if parsed.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return parsed


@dataclass(frozen=True)
class CourierCashProjection:
    order_version_id: str
    cash_execution_context_id: str
    quittung_status: str
    contract_version: str = CONTRACT_VERSION
    bar_required: bool = True

    def __post_init__(self) -> None:
        if self.contract_version != CONTRACT_VERSION:
            raise ValueError("unsupported contract version")
        if self.bar_required is not True:
            raise ValueError("cash projection must require BAR")
        if self.quittung_status not in {
            QUITTUNG_PRINTED_CURRENT,
            QUITTUNG_NOT_READY,
        }:
            raise ValueError("invalid Quittung status")
        _uuid(self.order_version_id, "order_version_id")
        _uuid(self.cash_execution_context_id, "cash_execution_context_id")

    def to_json(self) -> dict[str, object]:
        return {
            "contract_version": self.contract_version,
            "bar_required": True,
            "quittung_status": self.quittung_status,
            "order_version_id": self.order_version_id,
            "cash_execution_context_id": self.cash_execution_context_id,
        }


@dataclass(frozen=True)
class CourierCashCommand:
    idempotency_key: str
    event_type: str
    order_id: str
    assignment_id: str
    order_version_id: str
    cash_execution_context_id: str
    actor_id: str
    actor_role: str
    occurred_at: datetime
    not_received_reason: str | None
    note: str | None
    correction_reason: str | None
    correction_of_idempotency_key: str | None
    contract_version: str = CONTRACT_VERSION

    @classmethod
    def from_json(cls, value: object) -> CourierCashCommand:
        if not isinstance(value, dict) or set(value) != COMMAND_KEYS:
            raise ValueError("invalid cash command field set")
        if value["contract_version"] != CONTRACT_VERSION:
            raise UnsupportedCourierCashContractVersion()
        event_type = value["event_type"]
        if event_type not in EVENT_TYPES:
            raise ValueError("invalid cash event type")
        actor_role = value["actor_role"]
        if actor_role not in ACTOR_ROLES or actor_role not in _EVENT_ROLES[event_type]:
            raise ValueError("actor role not allowed for cash event")
        reason = value["not_received_reason"]
        note = _optional_text(value["note"], "note", 500)
        correction_reason = _optional_text(
            value["correction_reason"], "correction_reason", 500
        )
        correction_of = value["correction_of_idempotency_key"]
        if event_type == EVENT_NOT_RECEIVED:
            if reason not in NOT_RECEIVED_REASONS:
                raise ValueError("BAR_NOT_RECEIVED requires structured reason")
            if reason == "OTHER":
                if note is None:
                    raise ValueError("OTHER requires note")
            elif note is not None:
                raise ValueError("note is only allowed for OTHER")
            if correction_reason is not None or correction_of is not None:
                raise ValueError("not-received command cannot be correction")
        elif event_type == EVENT_CORRECTION:
            if reason is not None or note is not None:
                raise ValueError("correction cannot carry not-received fields")
            if correction_reason is None:
                raise ValueError("correction requires reason")
            correction_of = _uuid(correction_of, "correction_of_idempotency_key")
        elif any(
            item is not None
            for item in (reason, note, correction_reason, correction_of)
        ):
            raise ValueError("cash event carries fields that must be null")

        return cls(
            contract_version=CONTRACT_VERSION,
            idempotency_key=_uuid(value["idempotency_key"], "idempotency_key"),
            event_type=str(event_type),
            order_id=_uuid(value["order_id"], "order_id"),
            assignment_id=_uuid(value["assignment_id"], "assignment_id"),
            order_version_id=_uuid(value["order_version_id"], "order_version_id"),
            cash_execution_context_id=_uuid(
                value["cash_execution_context_id"], "cash_execution_context_id"
            ),
            actor_id=_text(value["actor_id"], "actor_id", 200),
            actor_role=str(actor_role),
            occurred_at=_date_time(value["occurred_at"], "occurred_at"),
            not_received_reason=str(reason) if reason is not None else None,
            note=note,
            correction_reason=correction_reason,
            correction_of_idempotency_key=(
                str(correction_of) if correction_of is not None else None
            ),
        )

    def to_json(self) -> dict[str, object]:
        return {
            "contract_version": self.contract_version,
            "idempotency_key": self.idempotency_key,
            "event_type": self.event_type,
            "order_id": self.order_id,
            "assignment_id": self.assignment_id,
            "order_version_id": self.order_version_id,
            "cash_execution_context_id": self.cash_execution_context_id,
            "actor_id": self.actor_id,
            "actor_role": self.actor_role,
            "occurred_at": self.occurred_at.isoformat(),
            "not_received_reason": self.not_received_reason,
            "note": self.note,
            "correction_reason": self.correction_reason,
            "correction_of_idempotency_key": self.correction_of_idempotency_key,
        }


@dataclass(frozen=True)
class CourierCashResult:
    event_id: str
    idempotency_key: str
    order_id: str
    cash_state: str
    recorded_at: datetime
    contract_version: str = CONTRACT_VERSION

    def to_json(self) -> dict[str, object]:
        return {
            "contract_version": self.contract_version,
            "event_id": self.event_id,
            "idempotency_key": self.idempotency_key,
            "order_id": self.order_id,
            "cash_state": self.cash_state,
            "recorded_at": self.recorded_at.isoformat(),
        }


@dataclass(frozen=True)
class CourierCashStoredEvent:
    sequence: int
    event_id: str
    idempotency_key: str
    request_fingerprint: str
    request_json: str
    response_json: str
    order_id: str
    assignment_id: str
    order_version_id: str
    cash_execution_context_id: str
    event_type: str
    actor_id: str
    actor_role: str
    occurred_at: datetime
    recorded_at: datetime
    from_state: str
    to_state: str
    not_received_reason: str | None
    note: str | None
    correction_reason: str | None
    correction_of_idempotency_key: str | None

    def result(self) -> CourierCashResult:
        import json

        value = json.loads(self.response_json)
        return CourierCashResult(
            contract_version=str(value["contract_version"]),
            event_id=str(value["event_id"]),
            idempotency_key=str(value["idempotency_key"]),
            order_id=str(value["order_id"]),
            cash_state=str(value["cash_state"]),
            recorded_at=_date_time(value["recorded_at"], "recorded_at"),
        )


class UnsupportedCourierCashContractVersion(ValueError):
    pass
