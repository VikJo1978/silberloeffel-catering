"""Compact office/Core progression review summary — Slice B11 (read-only derived; not persisted)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OrderProgressionReviewSummary:
    """Single compact derived read for inspection; not release or operational activation truth."""

    order_id: str
    latest_order_version_id: str | None
    candidate_order_version_id: str | None
    blocked: bool
    eligible_for_progression_review: bool
    reason_count: int
    reasons: tuple[str, ...]
