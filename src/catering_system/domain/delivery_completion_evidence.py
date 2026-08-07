"""Append-only delivery completion facts — Slice 6."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class DeliveryCompletionEvidence:
    delivery_completion_evidence_id: str
    order_id: str
    order_version_id: str
    completed_at: datetime
    recorded_at: datetime
    recorded_by: str
    evidence_reference: str
