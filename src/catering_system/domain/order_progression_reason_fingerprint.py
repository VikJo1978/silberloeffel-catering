"""Deterministic reason fingerprint from B14 export — Slice B24 (read-only derived; not persisted)."""

from __future__ import annotations

from dataclasses import dataclass

from catering_system.domain.order_progression_export import OrderProgressionExport


def derive_order_progression_reason_fingerprint(ex: OrderProgressionExport) -> str:
    """Join ex.reasons in tuple order with '|'; empty tuple → 'none'."""
    if not ex.reasons:
        return "none"
    return "|".join(ex.reasons)


@dataclass(frozen=True)
class OrderProgressionReasonFingerprint:
    """order_id plus derived reason fingerprint for compare/debug/group; no new operational truth."""

    order_id: str
    reason_fingerprint: str

    @classmethod
    def from_export(cls, ex: OrderProgressionExport) -> OrderProgressionReasonFingerprint:
        return cls(
            order_id=ex.order_id,
            reason_fingerprint=derive_order_progression_reason_fingerprint(ex),
        )
