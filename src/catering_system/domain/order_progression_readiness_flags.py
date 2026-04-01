"""Boolean readiness summary from B14 export — Slice B25 (read-only derived; not persisted)."""

from __future__ import annotations

from dataclasses import dataclass

from catering_system.domain.order_progression_export import OrderProgressionExport


@dataclass(frozen=True)
class OrderProgressionReadinessFlags:
    """Minimal derived flags for read-side checks; no new operational truth."""

    order_id: str
    has_candidate: bool
    has_latest_version: bool
    is_blocked: bool
    is_consistent: bool
    has_reasons: bool
    is_eligible: bool

    @classmethod
    def from_export(cls, ex: OrderProgressionExport) -> OrderProgressionReadinessFlags:
        return cls(
            order_id=ex.order_id,
            has_candidate=ex.candidate_order_version_id is not None,
            has_latest_version=ex.latest_order_version_id is not None,
            is_blocked=ex.blocked,
            is_consistent=ex.consistent,
            has_reasons=ex.reason_count > 0,
            is_eligible=ex.eligible_for_progression_review,
        )
