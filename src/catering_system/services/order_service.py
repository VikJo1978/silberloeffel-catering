"""Core order service — inquiry conversion (B1) and version history (B2)."""

from __future__ import annotations

import logging
import uuid
from dataclasses import replace
from datetime import date, datetime, timezone

from catering_system.domain.inquiry import Inquiry, validate_planning_mode
from catering_system.domain.order import Order, OrderVersion
from catering_system.repositories.order_repository import OrderRepository

_log = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class OrderService:
    """Core-owned Order lifecycle: initial conversion (B1), successor versions (B2)."""

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

    def create_relevant_order_change_version(
        self,
        order: Order,
        *,
        event_date: date,
        time_window_text: str,
        location_text: str,
        guest_count_estimate: int | None,
        planning_mode: str,
    ) -> OrderVersion:
        """Append a new OrderVersion; increments version_number; does not select any version as active."""
        current = self._order_repository.get_order(order.order_id)
        if current is None:
            raise ValueError(f"no order with id {order.order_id!r}")
        existing = self._order_repository.list_order_versions(order.order_id)
        next_num = max((v.version_number for v in existing), default=0) + 1
        now = _utc_now()
        pm = validate_planning_mode(planning_mode)
        version = OrderVersion(
            order_version_id=str(uuid.uuid4()),
            order_id=order.order_id,
            version_number=next_num,
            created_at=now,
            event_date=event_date,
            time_window_text=time_window_text,
            location_text=location_text,
            guest_count_estimate=guest_count_estimate,
            planning_mode=pm,
        )
        self._order_repository.save_order_version(version)
        self._order_repository.update_order(
            replace(current, updated_at=now),
        )
        _log.info(
            "create_relevant_order_change_version order_id=%s version=%s",
            order.order_id,
            version.version_number,
        )
        return version
