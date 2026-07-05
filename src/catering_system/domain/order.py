"""Order / OrderVersion — Slice B1/B2 Core operational truth baseline (minimal).

B3 adds no activation or selection fields; B6 adds optional candidate_order_version_id
only (office-side progression hint, not effective truth).
OPERATIONAL_CORE_EXECUTION_PACK_V1 (§7) adds kitchen_print_confirmed_at on
OrderVersion and effective_order_version_id on Order; STORNO_EXECUTION_PACK_V1
adds cancelled_at on Order. These three are the only operational fields.
Do not add any further status/selection field (is_active, is_effective,
selected_version_id, release_ready flags, ...) outside an accepted execution pack.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from catering_system.domain.inquiry import PlanningMode


@dataclass(frozen=True)
class Order:
    """Core-owned order aggregate root. Operational truth lives here, not in CRM."""

    order_id: str
    source_inquiry_id: str
    created_at: datetime
    updated_at: datetime
    candidate_order_version_id: str | None = None
    effective_order_version_id: str | None = None
    cancelled_at: datetime | None = None


@dataclass(frozen=True)
class OrderVersion:
    """Immutable version snapshot under Core (B1: initial v1; B2: further versions, no activation)."""

    order_version_id: str
    order_id: str
    version_number: int
    created_at: datetime
    event_date: date
    time_window_text: str
    location_text: str
    guest_count_estimate: int | None
    planning_mode: PlanningMode
    kitchen_print_confirmed_at: datetime | None = None
