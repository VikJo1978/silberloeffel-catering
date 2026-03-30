"""Flat progression export DTO from bundle — Slice B14 (read-only derived; not persisted)."""

from __future__ import annotations

from dataclasses import dataclass

from catering_system.domain.order_progression_bundle import OrderProgressionBundle


@dataclass(frozen=True)
class OrderProgressionExport:
    """Serializable-friendly flattening of B13 bundle; no new operational or release truth."""

    order_id: str
    latest_order_version_id: str | None
    candidate_order_version_id: str | None
    blocked: bool
    eligible_for_progression_review: bool
    consistent: bool
    reason_count: int
    reasons: tuple[str, ...]

    @classmethod
    def from_bundle(cls, bundle: OrderProgressionBundle) -> OrderProgressionExport:
        """Maps only checkpoint, review summary, and consistency check fields from an existing bundle."""
        cp = bundle.checkpoint
        sm = bundle.review_summary
        cc = bundle.consistency_check
        return cls(
            order_id=bundle.order_id,
            latest_order_version_id=cp.latest_order_version_id,
            candidate_order_version_id=cp.candidate_order_version_id,
            blocked=cp.blocked,
            eligible_for_progression_review=cp.eligible_for_progression_review,
            consistent=cc.consistent,
            reason_count=sm.reason_count,
            reasons=cp.reasons,
        )
