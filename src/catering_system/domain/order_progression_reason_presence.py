"""Minimal reason presence from B14 export — Slice B26 (read-only derived; not persisted)."""

from __future__ import annotations

from dataclasses import dataclass

from catering_system.domain.order_progression_export import OrderProgressionExport


@dataclass(frozen=True)
class OrderProgressionReasonPresence:
    """Whether the export carries any reasons, by reason_count only; no new operational truth."""

    order_id: str
    has_reasons: bool

    @classmethod
    def from_export(cls, ex: OrderProgressionExport) -> OrderProgressionReasonPresence:
        return cls(order_id=ex.order_id, has_reasons=ex.reason_count > 0)
