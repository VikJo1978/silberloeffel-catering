"""Kitchen print attempt facts and pure state derivation (Phase 3 / Slice 3A).

The model is an append-only attempt history with additive immutable facts for
one immutable OrderVersion. A row may receive new lifecycle timestamps, but a
recorded fact cannot be rewritten or removed. There is deliberately no
persisted general-purpose status enum. ``derive_kitchen_print_job_state``
computes the current state from those facts, Core time, and the owning Order's
cancellation fact.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

PROVISIONAL_PRINT_ACCEPTANCE_TIMEOUT = timedelta(seconds=30)
PROVISIONAL_PRINT_ACK_TIMEOUT = timedelta(minutes=5)

KITCHEN_PRINT_REJECTION_CODES = frozenset(
    {
        "render_failed",
        "spool_rejected",
        "printer_unavailable",
        "invalid_printer_configuration",
        "order_cancelled",
    }
)

KitchenPrintJobState = Literal[
    "cancelled",
    "confirmed",
    "rejected",
    "superseded",
    "ack_overdue",
    "awaiting_ack",
    "acceptance_overdue",
    "awaiting_acceptance",
]


@dataclass(frozen=True)
class KitchenPrintPolicy:
    """Configurable deadlines with explicitly provisional defaults.

    Slice 3A needs deterministic values to persist deadlines and test state
    derivation. These defaults are not an accepted production SLA; callers may
    inject different positive durations without changing domain code.
    """

    acceptance_timeout: timedelta = PROVISIONAL_PRINT_ACCEPTANCE_TIMEOUT
    acknowledgment_timeout: timedelta = PROVISIONAL_PRINT_ACK_TIMEOUT

    def __post_init__(self) -> None:
        if self.acceptance_timeout <= timedelta(0):
            raise ValueError("acceptance_timeout must be positive")
        if self.acknowledgment_timeout <= timedelta(0):
            raise ValueError("acknowledgment_timeout must be positive")


@dataclass(frozen=True)
class KitchenPrintJob:
    print_job_id: str
    order_id: str
    order_version_id: str
    attempt_number: int
    requested_at: datetime
    accept_deadline_at: datetime
    accepted_at: datetime | None = None
    ack_deadline_at: datetime | None = None
    rejected_at: datetime | None = None
    rejection_code: str | None = None
    acknowledged_at: datetime | None = None
    superseded_at: datetime | None = None
    supersedes_print_job_id: str | None = None

    def __post_init__(self) -> None:
        for name in ("print_job_id", "order_id", "order_version_id"):
            if not getattr(self, name):
                raise ValueError(f"{name} must not be empty")
        _require_uuid4("print_job_id", self.print_job_id)
        if self.supersedes_print_job_id is not None:
            _require_uuid4("supersedes_print_job_id", self.supersedes_print_job_id)
        if self.attempt_number < 1:
            raise ValueError("attempt_number must be positive")

        for field in fields(self):
            value = getattr(self, field.name)
            if isinstance(value, datetime):
                _require_utc(field.name, value)

        if self.accept_deadline_at <= self.requested_at:
            raise ValueError("accept_deadline_at must be after requested_at")
        if (self.accepted_at is None) != (self.ack_deadline_at is None):
            raise ValueError("accepted_at and ack_deadline_at must be set together")
        if self.accepted_at is not None:
            assert self.ack_deadline_at is not None
            if self.accepted_at < self.requested_at:
                raise ValueError("accepted_at must not predate requested_at")
            if self.ack_deadline_at <= self.accepted_at:
                raise ValueError("ack_deadline_at must be after accepted_at")
        if (self.rejected_at is None) != (self.rejection_code is None):
            raise ValueError("rejected_at and rejection_code must be set together")
        if (
            self.rejection_code is not None
            and self.rejection_code not in KITCHEN_PRINT_REJECTION_CODES
        ):
            raise ValueError(f"unsupported rejection_code {self.rejection_code!r}")
        if self.rejected_at is not None and self.rejected_at < self.requested_at:
            raise ValueError("rejected_at must not predate requested_at")
        if (
            self.rejected_at is not None
            and self.accepted_at is not None
            and self.rejected_at < self.accepted_at
        ):
            raise ValueError("rejected_at must not predate accepted_at")
        if self.acknowledged_at is not None:
            if self.accepted_at is None:
                raise ValueError("acknowledgement requires technical acceptance")
            if self.acknowledged_at < self.accepted_at:
                raise ValueError("acknowledged_at must not predate accepted_at")
            if self.rejected_at is not None or self.superseded_at is not None:
                raise ValueError("acknowledgement conflicts with terminal job facts")
        if self.superseded_at is not None:
            if self.superseded_at < self.requested_at:
                raise ValueError("superseded_at must not predate requested_at")
            if self.rejected_at is not None or self.acknowledged_at is not None:
                raise ValueError("supersession conflicts with terminal job facts")


_IMMUTABLE_JOB_FIELDS = (
    "print_job_id",
    "order_id",
    "order_version_id",
    "attempt_number",
    "requested_at",
    "accept_deadline_at",
    "supersedes_print_job_id",
)

_ADDITIVE_JOB_FIELDS = (
    "accepted_at",
    "ack_deadline_at",
    "rejected_at",
    "rejection_code",
    "acknowledged_at",
    "superseded_at",
)


def validate_kitchen_print_job_transition(
    previous: KitchenPrintJob, updated: KitchenPrintJob
) -> None:
    """Reject any rewrite/removal of an existing print-job fact."""

    for name in _IMMUTABLE_JOB_FIELDS:
        if getattr(previous, name) != getattr(updated, name):
            raise ValueError(f"print job field {name} is immutable")
    for name in _ADDITIVE_JOB_FIELDS:
        old_value = getattr(previous, name)
        if old_value is not None and getattr(updated, name) != old_value:
            raise ValueError(f"print job fact {name} is not revocable")


def derive_kitchen_print_job_state(
    job: KitchenPrintJob,
    *,
    now: datetime,
    order_cancelled: bool = False,
) -> KitchenPrintJobState:
    """Pure state derivation; persists nothing and uses only supplied facts."""

    _require_utc("now", now)
    if order_cancelled and job.acknowledged_at is None:
        return "cancelled"
    if job.acknowledged_at is not None:
        return "confirmed"
    if job.rejected_at is not None:
        return "rejected"
    if job.superseded_at is not None:
        return "superseded"
    if job.accepted_at is not None:
        assert job.ack_deadline_at is not None
        if now >= job.ack_deadline_at:
            return "ack_overdue"
        return "awaiting_ack"
    if now >= job.accept_deadline_at:
        return "acceptance_overdue"
    return "awaiting_acceptance"


def _require_utc(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be timezone-aware UTC")


def _require_uuid4(name: str, value: str) -> None:
    try:
        parsed = UUID(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be UUID4") from exc
    if parsed.version != 4 or str(parsed) != value:
        raise ValueError(f"{name} must be canonical UUID4")
