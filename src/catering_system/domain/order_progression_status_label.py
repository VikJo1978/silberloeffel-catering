"""Minimal status label from B14 export — Slice B19 (read-only derived; not persisted)."""

from __future__ import annotations

from dataclasses import dataclass

from catering_system.domain.order_progression_export import OrderProgressionExport


def derive_order_progression_status_label(ex: OrderProgressionExport) -> str:
    """Deterministic label from export flags only: inconsistent → blocked → eligible → not_eligible."""
    if not ex.consistent:
        return "inconsistent"
    if ex.blocked:
        return "blocked"
    if ex.eligible_for_progression_review:
        return "eligible"
    return "not_eligible"


@dataclass(frozen=True)
class OrderProgressionStatusLabel:
    """order_id plus a single derived label string; no new operational truth."""

    order_id: str
    status_label: str

    @classmethod
    def from_export(cls, ex: OrderProgressionExport) -> OrderProgressionStatusLabel:
        return cls(order_id=ex.order_id, status_label=derive_order_progression_status_label(ex))
