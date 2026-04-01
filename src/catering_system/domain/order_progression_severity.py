"""Minimal severity level from B14 export — Slice B21 (read-only derived; not persisted)."""

from __future__ import annotations

from dataclasses import dataclass

from catering_system.domain.order_progression_export import OrderProgressionExport


def derive_order_progression_severity(ex: OrderProgressionExport) -> str:
    """Deterministic severity from export facts only; fixed priority (worst first)."""
    if not ex.consistent:
        return "critical"
    if ex.blocked:
        return "high"
    if ex.reason_count > 0:
        return "elevated"
    if ex.eligible_for_progression_review:
        return "normal"
    return "low"


@dataclass(frozen=True)
class OrderProgressionSeverity:
    """order_id plus a single derived severity string for UI sort/filter; no new operational truth."""

    order_id: str
    severity: str

    @classmethod
    def from_export(cls, ex: OrderProgressionExport) -> OrderProgressionSeverity:
        return cls(order_id=ex.order_id, severity=derive_order_progression_severity(ex))
