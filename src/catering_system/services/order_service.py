"""Core order service — inquiry conversion (B1), version history (B2), explicit reads (B3), candidate (B6).

B3 does not add activation or selection fields on Order / OrderVersion. Do not add any field like:
is_active, is_effective, active_version_id, effective_version_id, selected_version_id, release_ready flags.
B6 candidate_order_version_id is office-side progression only, not effective operational truth.
If such semantics are needed later, they belong to a later Slice B package, not B3/B6.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import replace
from datetime import date, datetime, timezone

from catering_system.domain.inquiry import Inquiry, inquiry_allows_order_conversion, validate_planning_mode
from catering_system.domain.order import Order, OrderVersion
from catering_system.repositories.order_repository import OrderRepository

_log = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class OrderService:
    """Core-owned Order lifecycle: conversion (B1/B5), versions (B2), history reads (B3), candidate (B6)."""

    def __init__(self, order_repository: OrderRepository) -> None:
        self._order_repository = order_repository

    def convert_inquiry_to_order(self, inquiry: Inquiry) -> tuple[Order, OrderVersion]:
        """ConvertInquiryToOrder — Core ownership; does not mutate or delete the Inquiry.

        B5: blocked when call verification is required and not verified (pending / failed / blocked).
        """
        if not inquiry_allows_order_conversion(inquiry):
            raise ValueError(
                "inquiry_to_order conversion blocked: call verification required and not verified "
                f"(inquiry_id={inquiry.inquiry_id!r}, "
                f"call_verification_required={inquiry.call_verification_required!r}, "
                f"call_verification_status={inquiry.call_verification_status!r})"
            )
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

    def list_order_versions(self, order_id: str) -> list[OrderVersion]:
        """Return all versions for an order, ordered by version_number (append-only history)."""
        return self._order_repository.list_order_versions(order_id)

    def get_latest_order_version(self, order_id: str) -> OrderVersion | None:
        """Latest by highest version_number in stored history only; not operational activation (deferred).

        Returns None when there are no versions (e.g. unknown order_id); does not infer an active row.
        """
        rows = self._order_repository.list_order_versions(order_id)
        if not rows:
            return None
        return rows[-1]

    def set_candidate_order_version(self, order_id: str, order_version_id: str) -> Order:
        """B6: set the single office-side candidate version; does not select an effective operational version."""
        current = self._order_repository.get_order(order_id)
        if current is None:
            raise ValueError(f"no order with id {order_id!r}")
        ver = self._order_repository.get_order_version(order_version_id)
        if ver is None or ver.order_id != order_id:
            raise ValueError(
                f"order_version_id {order_version_id!r} is not a version of order {order_id!r}"
            )
        now = _utc_now()
        updated = replace(current, candidate_order_version_id=order_version_id, updated_at=now)
        self._order_repository.update_order(updated)
        _log.info(
            "set_candidate_order_version order_id=%s candidate_order_version_id=%s",
            order_id,
            order_version_id,
        )
        return updated

    def get_candidate_order_version(self, order_id: str) -> OrderVersion | None:
        """B6: resolve the office-side candidate; None if unset or unknown order."""
        order = self._order_repository.get_order(order_id)
        if order is None:
            return None
        cid = order.candidate_order_version_id
        if not cid:
            return None
        return self._order_repository.get_order_version(cid)
