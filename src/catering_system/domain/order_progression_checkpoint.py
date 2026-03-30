"""On-demand office/Core progression checkpoint snapshot — Slice B10 (read-only derived; not persisted)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OrderProgressionCheckpoint:
    """Single derived snapshot for review/logging/debug; not operational or release truth."""

    order_id: str
    latest_order_version_id: str | None
    candidate_order_version_id: str | None
    blocked: bool
    reasons: tuple[str, ...]
    eligible_for_progression_review: bool
