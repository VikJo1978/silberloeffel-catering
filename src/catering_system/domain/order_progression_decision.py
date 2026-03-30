"""Office/Core progression eligibility decision — Slice B9 (derived only; not persisted)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OrderProgressionDecision:
    """Whether an order may be taken up for office-side progression review, from existing facts only."""

    order_id: str
    eligible_for_progression_review: bool
    reasons: tuple[str, ...]
    candidate_order_version_id: str | None
