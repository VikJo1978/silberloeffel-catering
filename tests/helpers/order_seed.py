"""Test-only Order seeding — does not use production Inquiry→Order create."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from catering_system.domain.inquiry import Inquiry
from catering_system.domain.order import Order, OrderVersion
from catering_system.repositories.order_repository import OrderRepository


def seed_order(
    order_repository: OrderRepository,
    inquiry: Inquiry,
    *,
    order_id: str | None = None,
    order_version_id: str | None = None,
    created_at: datetime | None = None,
) -> tuple[Order, OrderVersion]:
    """Persist Order + v1 from Inquiry facts via the repository (fixture only)."""
    now = created_at or datetime.now(timezone.utc)
    oid = order_id or str(uuid.uuid4())
    order = Order(
        order_id=oid,
        source_inquiry_id=inquiry.inquiry_id,
        created_at=now,
        updated_at=now,
    )
    version = OrderVersion(
        order_version_id=order_version_id or str(uuid.uuid4()),
        order_id=oid,
        version_number=1,
        created_at=now,
        event_date=inquiry.event_date,
        time_window_text=inquiry.time_window_text,
        location_text=inquiry.location_text,
        guest_count_estimate=inquiry.guest_count_estimate,
        planning_mode=inquiry.planning_mode,
    )
    order_repository.save_order_with_initial_version(order, version)
    return order, version
