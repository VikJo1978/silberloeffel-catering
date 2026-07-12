"""Composed read-only summary from checkpoint + already derived B21/B23–B25 — Slice B27 (read-only; not persisted)."""

from __future__ import annotations

from dataclasses import dataclass

from catering_system.domain.order_progression_checkpoint import (
    OrderProgressionCheckpoint,
)
from catering_system.domain.order_progression_facts import OrderProgressionFacts
from catering_system.domain.order_progression_reason_fingerprint import (
    OrderProgressionReasonFingerprint,
)
from catering_system.domain.order_progression_readiness_flags import (
    OrderProgressionReadinessFlags,
)
from catering_system.domain.order_progression_severity import OrderProgressionSeverity


@dataclass(frozen=True)
class OrderProgressionComposedDerivedReviewSummary:
    """Aggregates checkpoint ids/blocked with B21/B24/B25/B23-derived fields only; no new operational truth."""

    order_id: str
    latest_order_version_id: str | None
    candidate_order_version_id: str | None
    blocked: bool
    severity: str
    reason_fingerprint: str
    readiness_flags: OrderProgressionReadinessFlags
    facts_count: int

    @classmethod
    def compose(
        cls,
        checkpoint: OrderProgressionCheckpoint,
        severity: OrderProgressionSeverity,
        reason_fingerprint: OrderProgressionReasonFingerprint,
        readiness_flags: OrderProgressionReadinessFlags,
        facts: OrderProgressionFacts,
    ) -> OrderProgressionComposedDerivedReviewSummary:
        """facts_count = number of True values among the four B23 boolean fact fields."""
        facts_count = sum(
            1
            for v in (
                facts.has_reasons,
                facts.is_blocked,
                facts.is_consistent,
                facts.is_eligible,
            )
            if v
        )
        return cls(
            order_id=checkpoint.order_id,
            latest_order_version_id=checkpoint.latest_order_version_id,
            candidate_order_version_id=checkpoint.candidate_order_version_id,
            blocked=checkpoint.blocked,
            severity=severity.severity,
            reason_fingerprint=reason_fingerprint.reason_fingerprint,
            readiness_flags=readiness_flags,
            facts_count=facts_count,
        )
