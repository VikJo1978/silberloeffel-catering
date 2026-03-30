"""Order / OrderVersion — Slice B1/B2 Core operational truth baseline (minimal).

B3 does not add activation or selection fields. Do not add any field like:
is_active, is_effective, active_version_id, effective_version_id, selected_version_id.
If such semantics are needed later, they belong to a later Slice B package, not B3.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from catering_system.domain.inquiry import PlanningMode


@dataclass
class Order:
    """Core-owned order aggregate root. Operational truth lives here, not in CRM."""

    order_id: str
    source_inquiry_id: str
    created_at: datetime
    updated_at: datetime


@dataclass
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
