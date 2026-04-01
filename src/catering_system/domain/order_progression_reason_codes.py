"""Reason-code projection from B14 export — Slice B18 (read-only derived; not persisted)."""

from __future__ import annotations

from dataclasses import dataclass

from catering_system.domain.order_progression_export import OrderProgressionExport


@dataclass(frozen=True)
class OrderProgressionReasonCodes:
    """Minimal order_id + progression reason strings from export only; same tuple order as export."""

    order_id: str
    reason_count: int
    reasons: tuple[str, ...]

    @classmethod
    def from_export(cls, ex: OrderProgressionExport) -> OrderProgressionReasonCodes:
        return cls(
            order_id=ex.order_id,
            reason_count=ex.reason_count,
            reasons=ex.reasons,
        )
