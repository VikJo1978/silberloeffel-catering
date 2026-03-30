"""Bundled derived progression artifacts for one order — Slice B13 (read-only; not persisted)."""

from __future__ import annotations

from dataclasses import dataclass

from catering_system.domain.order_progression_checkpoint import OrderProgressionCheckpoint
from catering_system.domain.order_progression_consistency_check import OrderProgressionConsistencyCheck
from catering_system.domain.order_progression_decision import OrderProgressionDecision
from catering_system.domain.order_progression_review_summary import OrderProgressionReviewSummary
from catering_system.domain.order_progression_view import OrderProgressionView


@dataclass(frozen=True)
class OrderProgressionBundle:
    """References only existing B8–B12 read models; no new operational or release truth."""

    order_id: str
    view: OrderProgressionView
    decision: OrderProgressionDecision
    checkpoint: OrderProgressionCheckpoint
    review_summary: OrderProgressionReviewSummary
    consistency_check: OrderProgressionConsistencyCheck
