"""Transport DTOs for the kitchen print agent — no Core domain types."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ClaimDocument:
    content_type: str
    body: bytes


@dataclass(frozen=True)
class ClaimResponse:
    command_id: str
    print_job_id: str | None
    document: ClaimDocument | None


@dataclass(frozen=True)
class RejectResponse:
    command_id: str
    print_job_id: str
    rejection_code: str
