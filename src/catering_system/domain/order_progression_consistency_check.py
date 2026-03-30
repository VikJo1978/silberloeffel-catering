"""Derived progression layer consistency — Slice B12 (read-only; not persisted)."""

from __future__ import annotations

from dataclasses import dataclass

from catering_system.domain.order_progression_checkpoint import OrderProgressionCheckpoint
from catering_system.domain.order_progression_decision import OrderProgressionDecision
from catering_system.domain.order_progression_review_summary import OrderProgressionReviewSummary
from catering_system.domain.order_progression_view import OrderProgressionView


@dataclass(frozen=True)
class OrderProgressionConsistencyCheck:
    """Whether view, decision, checkpoint, and review summary agree; derived inspection only."""

    order_id: str
    consistent: bool
    reasons: tuple[str, ...]


def evaluate_order_progression_consistency(
    order_id: str,
    view: OrderProgressionView,
    decision: OrderProgressionDecision,
    checkpoint: OrderProgressionCheckpoint,
    summary: OrderProgressionReviewSummary,
) -> OrderProgressionConsistencyCheck:
    """Compares existing B8/B9/B10/B11 read models; does not consult repository or persistence."""
    r: list[str] = []
    if view.order_id != order_id:
        r.append("view.order_id differs from requested order_id")
    if decision.order_id != order_id:
        r.append("decision.order_id differs from requested order_id")
    if checkpoint.order_id != order_id:
        r.append("checkpoint.order_id differs from requested order_id")
    if summary.order_id != order_id:
        r.append("summary.order_id differs from requested order_id")
    latest_id = (
        view.latest_order_version.order_version_id
        if view.latest_order_version is not None
        else None
    )
    if checkpoint.latest_order_version_id != latest_id:
        r.append("checkpoint.latest_order_version_id != view.latest_order_version_id")
    if checkpoint.blocked != view.blocked:
        r.append("checkpoint.blocked != view.blocked")
    if checkpoint.reasons != view.reasons:
        r.append("checkpoint.reasons != view.reasons")
    if decision.reasons != view.reasons:
        r.append("decision.reasons != view.reasons")
    if checkpoint.eligible_for_progression_review != decision.eligible_for_progression_review:
        r.append("checkpoint.eligible_for_progression_review != decision.eligible_for_progression_review")
    if checkpoint.candidate_order_version_id != decision.candidate_order_version_id:
        r.append("checkpoint.candidate_order_version_id != decision.candidate_order_version_id")
    if summary.latest_order_version_id != checkpoint.latest_order_version_id:
        r.append("summary.latest_order_version_id != checkpoint.latest_order_version_id")
    if summary.candidate_order_version_id != checkpoint.candidate_order_version_id:
        r.append("summary.candidate_order_version_id != checkpoint.candidate_order_version_id")
    if summary.blocked != checkpoint.blocked:
        r.append("summary.blocked != checkpoint.blocked")
    if summary.eligible_for_progression_review != checkpoint.eligible_for_progression_review:
        r.append("summary.eligible_for_progression_review != checkpoint.eligible_for_progression_review")
    if summary.reasons != checkpoint.reasons:
        r.append("summary.reasons != checkpoint.reasons")
    if summary.reason_count != len(checkpoint.reasons):
        r.append("summary.reason_count != len(checkpoint.reasons)")
    return OrderProgressionConsistencyCheck(
        order_id=order_id,
        consistent=len(r) == 0,
        reasons=tuple(r),
    )
