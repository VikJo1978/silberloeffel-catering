"""Plain mapping view of B14 export — Slice B16 (read-only derived; not persisted)."""

from __future__ import annotations

from catering_system.domain.order_progression_export import OrderProgressionExport


def order_progression_export_to_dict(ex: OrderProgressionExport) -> dict[str, object]:
    """Maps export fields to built-in types only; stable key order."""
    return {
        "order_id": ex.order_id,
        "latest_order_version_id": ex.latest_order_version_id,
        "candidate_order_version_id": ex.candidate_order_version_id,
        "blocked": ex.blocked,
        "eligible_for_progression_review": ex.eligible_for_progression_review,
        "consistent": ex.consistent,
        "reason_count": ex.reason_count,
        "reasons": list(ex.reasons),
    }
