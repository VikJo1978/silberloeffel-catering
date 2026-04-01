"""Compact boolean facts from B14 export — Slice B23 (read-only derived; not persisted)."""

from __future__ import annotations

from dataclasses import dataclass

from catering_system.domain.order_progression_export import OrderProgressionExport


@dataclass(frozen=True)
class OrderProgressionFacts:
    """order_id plus derived flags for filter/debug/sort; no new operational truth."""

    order_id: str
    has_reasons: bool
    is_blocked: bool
    is_consistent: bool
    is_eligible: bool

    @classmethod
    def from_export(cls, ex: OrderProgressionExport) -> OrderProgressionFacts:
        return cls(
            order_id=ex.order_id,
            has_reasons=ex.reason_count > 0,
            is_blocked=ex.blocked,
            is_consistent=ex.consistent,
            is_eligible=ex.eligible_for_progression_review,
        )
