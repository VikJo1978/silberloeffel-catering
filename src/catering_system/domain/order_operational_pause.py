"""Order-level operational PAUSE — append-only audit events (Slice A1).

Active pause state is derived from event history, not from a mutable flag.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

OperationalPauseAction = Literal["paused", "resumed"]

OPERATIONAL_PAUSE_REASON_CODES = frozenset(
    {
        "manual_hold",
        "customer_request",
        "payment_dispute",
        "operational_review",
        "other",
    }
)

OPERATIONAL_RESUME_REASON_CODES = frozenset(
    {
        "operator_cleared",
        "customer_confirmed",
        "issue_resolved",
        "other",
    }
)

MAX_PAUSE_NOTE_LEN = 2000
MAX_PAUSE_REASON_CODE_LEN = 100
MAX_PAUSE_ACTOR_LEN = 200


@dataclass(frozen=True)
class OrderOperationalPauseEvent:
    """One append-only pause/resume fact for an Order."""

    pause_event_id: str
    order_id: str
    action: OperationalPauseAction
    reason_code: str
    note: str | None
    actor_reference: str
    occurred_at: datetime
    command_id: str
    resumes_pause_event_id: str | None = None

    def __post_init__(self) -> None:
        if self.action not in ("paused", "resumed"):
            raise ValueError("invalid pause action")
        if not self.pause_event_id:
            raise ValueError("pause_event_id is required")
        if not self.order_id:
            raise ValueError("order_id is required")
        if not self.reason_code:
            raise ValueError("reason_code is required")
        if len(self.reason_code) > MAX_PAUSE_REASON_CODE_LEN:
            raise ValueError("reason_code exceeds length limit")
        if not self.actor_reference:
            raise ValueError("actor_reference is required")
        if len(self.actor_reference) > MAX_PAUSE_ACTOR_LEN:
            raise ValueError("actor_reference exceeds length limit")
        if self.note is not None and len(self.note) > MAX_PAUSE_NOTE_LEN:
            raise ValueError("note exceeds length limit")
        if not self.command_id:
            raise ValueError("command_id is required")
        if self.action == "paused":
            if self.resumes_pause_event_id is not None:
                raise ValueError("paused event must not resume another pause")
        elif self.resumes_pause_event_id is None:
            raise ValueError("resumed event must reference the active pause")


def validate_pause_reason_code(reason_code: str) -> str:
    if reason_code not in OPERATIONAL_PAUSE_REASON_CODES:
        raise ValueError(f"invalid pause reason_code {reason_code!r}")
    return reason_code


def validate_resume_reason_code(reason_code: str) -> str:
    if reason_code not in OPERATIONAL_RESUME_REASON_CODES:
        raise ValueError(f"invalid resume reason_code {reason_code!r}")
    return reason_code


def derive_active_pause(
    events: tuple[OrderOperationalPauseEvent, ...],
) -> OrderOperationalPauseEvent | None:
    """Return the active paused event, if any, from append-only history."""
    active: OrderOperationalPauseEvent | None = None
    for event in sorted(events, key=lambda row: (row.occurred_at, row.pause_event_id)):
        if event.action == "paused":
            active = event
        elif (
            active is not None and event.resumes_pause_event_id == active.pause_event_id
        ):
            active = None
    return active


def derive_operational_pause_projection(
    events: tuple[OrderOperationalPauseEvent, ...],
) -> dict[str, object]:
    """Read-model projection for API/Panel concurrency and display."""
    ordered = tuple(
        sorted(events, key=lambda row: (row.occurred_at, row.pause_event_id))
    )
    latest = ordered[-1] if ordered else None
    active = derive_active_pause(ordered)
    if active is None:
        return {
            "active": False,
            "latest_pause_event_id": latest.pause_event_id if latest else None,
        }
    assert latest is not None
    return {
        "active": True,
        "current_pause_event_id": active.pause_event_id,
        "latest_pause_event_id": latest.pause_event_id,
        "reason_code": active.reason_code,
        "note": active.note,
        "paused_at": active.occurred_at.isoformat(),
        "actor_reference": active.actor_reference,
    }
