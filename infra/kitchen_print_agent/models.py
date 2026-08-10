"""Transport DTOs for the kitchen print agent — no Core domain types."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ClaimDocument:
    content_type: str
    body: bytes


@dataclass(frozen=True)
class ClaimResponse:
    command_id: str
    print_job_id: str | None
    ack_deadline_at: datetime | None
    document: ClaimDocument | None


@dataclass(frozen=True)
class RejectResponse:
    command_id: str
    print_job_id: str
    rejection_code: str


@dataclass(frozen=True)
class AcknowledgeResponse:
    command_id: str
    print_job_id: str
    acknowledged_at: datetime
