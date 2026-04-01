"""Deterministic human-readable text from B14 export — Slice B15 (read-only derived; not persisted)."""

from __future__ import annotations

from catering_system.domain.order_progression_export import OrderProgressionExport


def format_order_progression_export_text(ex: OrderProgressionExport) -> str:
    """Builds a compact multi-line summary from export fields only; stable key order and reason order."""

    def _opt_id(v: str | None) -> str:
        return "none" if v is None else v

    lines = [
        f"order_id: {ex.order_id}",
        f"latest_order_version_id: {_opt_id(ex.latest_order_version_id)}",
        f"candidate_order_version_id: {_opt_id(ex.candidate_order_version_id)}",
        f"blocked: {str(ex.blocked).lower()}",
        f"eligible_for_progression_review: {str(ex.eligible_for_progression_review).lower()}",
        f"consistent: {str(ex.consistent).lower()}",
        f"reason_count: {ex.reason_count}",
    ]
    for i, r in enumerate(ex.reasons):
        lines.append(f"reason[{i}]: {r}")
    return "\n".join(lines) + "\n"
