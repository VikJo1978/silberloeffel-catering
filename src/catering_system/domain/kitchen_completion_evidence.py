"""Append-only kitchen execution completion facts — Slice 5."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class KitchenCompletionEvidence:
    kitchen_completion_evidence_id: str
    order_id: str
    order_version_id: str
    completed_at: datetime
    recorded_at: datetime
    recorded_by: str
    evidence_reference: str
