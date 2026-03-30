"""Composed order progression read — Slice B8 (derived only; not persisted)."""

from __future__ import annotations

from dataclasses import dataclass

from catering_system.domain.order import OrderVersion


@dataclass(frozen=True)
class OrderProgressionView:
    """Office/Core visibility: latest history, candidate snapshot, candidate-progression blocked evaluation."""

    order_id: str
    latest_order_version: OrderVersion | None
    candidate_order_version: OrderVersion | None
    blocked: bool
    reasons: tuple[str, ...]
