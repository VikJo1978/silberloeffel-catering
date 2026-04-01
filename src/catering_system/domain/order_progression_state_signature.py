"""Compact state signature string from B14 export — Slice B22 (read-only derived; not persisted)."""

from __future__ import annotations

from dataclasses import dataclass

from catering_system.domain.order_progression_export import OrderProgressionExport


def derive_order_progression_state_signature(ex: OrderProgressionExport) -> str:
    """Deterministic signature from export scalar flags only; fixed field order."""
    return (
        f"blocked={str(ex.blocked).lower()}"
        f"|eligible_for_progression_review={str(ex.eligible_for_progression_review).lower()}"
        f"|consistent={str(ex.consistent).lower()}"
        f"|reason_count={ex.reason_count}"
    )


@dataclass(frozen=True)
class OrderProgressionStateSignature:
    """order_id plus derived signature for debug/compare/filter; no new operational truth."""

    order_id: str
    state_signature: str

    @classmethod
    def from_export(cls, ex: OrderProgressionExport) -> OrderProgressionStateSignature:
        return cls(order_id=ex.order_id, state_signature=derive_order_progression_state_signature(ex))
