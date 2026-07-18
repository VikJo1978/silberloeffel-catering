"""Order / OrderVersion — Slice B1/B2 Core operational truth baseline (minimal).

B3 adds no activation or selection fields; B6 adds optional candidate_order_version_id
only (office-side progression hint, not effective truth).
OPERATIONAL_CORE_EXECUTION_PACK_V1 (§7) adds kitchen_print_confirmed_at on
OrderVersion and effective_order_version_id on Order; STORNO_EXECUTION_PACK_V1
adds cancelled_at on Order. EFFECTIVE_ORDER_VERSION_CHANGE_GATE_V1 adds only
immutable change provenance to OrderVersion. No stored status/selection field
(is_active, is_effective, release_ready, superseded, ...) belongs here.
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
    """Immutable operational snapshot plus one additive kitchen-confirmation fact."""

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
    parent_order_version_id: str | None = None
    created_by: str | None = None
    change_reason: str | None = None
    changed_fields: tuple[str, ...] = ()


def is_order_version_superseded(
    order: Order,
    version: OrderVersion,
    versions: list[OrderVersion],
) -> bool:
    """Derive supersession without mutating an earlier candidate snapshot."""
    if version.parent_order_version_id is None:
        return False
    if version.order_version_id in {
        order.candidate_order_version_id,
        order.effective_order_version_id,
    }:
        return False
    return any(
        later.parent_order_version_id == version.parent_order_version_id
        and later.version_number > version.version_number
        for later in versions
    )
