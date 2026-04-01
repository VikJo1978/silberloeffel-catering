"""Compact badge list from B14 export — Slice B20 (read-only derived; not persisted)."""

from __future__ import annotations

from dataclasses import dataclass

from catering_system.domain.order_progression_export import OrderProgressionExport


def derive_order_progression_badges(ex: OrderProgressionExport) -> tuple[str, ...]:
    """Deterministic badge strings from export facts only; fixed emission order."""
    out: list[str] = []
    if ex.blocked:
        out.append("blocked")
    if ex.eligible_for_progression_review:
        out.append("eligible_for_progression_review")
    if ex.consistent:
        out.append("consistent")
    else:
        out.append("inconsistent")
    if ex.reason_count > 0:
        out.append("reasons_present")
    return tuple(out)


@dataclass(frozen=True)
class OrderProgressionBadges:
    """order_id plus derived badge strings for UI filtering; no new operational truth."""

    order_id: str
    badges: tuple[str, ...]

    @classmethod
    def from_export(cls, ex: OrderProgressionExport) -> OrderProgressionBadges:
        return cls(order_id=ex.order_id, badges=derive_order_progression_badges(ex))
