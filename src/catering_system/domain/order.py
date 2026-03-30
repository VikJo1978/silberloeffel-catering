"""Order / OrderVersion — Slice B1/B2 Core operational truth baseline (minimal)."""

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
