"""Core order service — inquiry-to-order conversion (B1 only)."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from catering_system.domain.inquiry import Inquiry
from catering_system.domain.order import Order, OrderVersion
from catering_system.repositories.order_repository import OrderRepository

_log = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class OrderService:
    """Creates Core-owned Order + initial OrderVersion from an Inquiry (B1 scope)."""

    def __init__(self, order_repository: OrderRepository) -> None:
        self._order_repository = order_repository

    def convert_inquiry_to_order(self, inquiry: Inquiry) -> tuple[Order, OrderVersion]:
        """ConvertInquiryToOrder — Core ownership; does not mutate or delete the Inquiry."""
        now = _utc_now()
        order_id = str(uuid.uuid4())
        order = Order(
            order_id=order_id,
            source_inquiry_id=inquiry.inquiry_id,
            created_at=now,
            updated_at=now,
        )
        version = OrderVersion(
            order_version_id=str(uuid.uuid4()),
            order_id=order_id,
            version_number=1,
            created_at=now,
            event_date=inquiry.event_date,
            time_window_text=inquiry.time_window_text,
            location_text=inquiry.location_text,
            guest_count_estimate=inquiry.guest_count_estimate,
            planning_mode=inquiry.planning_mode,
        )
        self._order_repository.save_order(order)
        self._order_repository.save_order_version(version)
        _log.info(
            "convert_inquiry_to_order inquiry_id=%s order_id=%s version=%s",
            inquiry.inquiry_id,
            order_id,
            version.version_number,
        )
        return order, version
