"""Core order service — inquiry conversion (B1), version history (B2), explicit reads (B3), candidate (B6).

B3 does not add activation or selection fields on Order / OrderVersion. Do not add any field like:
is_active, is_effective, active_version_id, effective_version_id, selected_version_id, release_ready flags.
B6 candidate_order_version_id is office-side progression only, not effective operational truth.
If such semantics are needed later, they belong to a later Slice B package, not B3/B6.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import replace
from datetime import date, datetime, timezone

from catering_system.domain.inquiry import (
    Inquiry,
    inquiry_allows_order_conversion,
    validate_planning_mode,
)
from catering_system.domain.inquiry_contact_completeness import (
    inquiry_contact_complete,
)
from catering_system.domain.offer import OfferVersion as CommercialOfferVersion
from catering_system.domain.operational_core_events import (
    OrderVersionCandidateSuperseded,
    OrderVersionChangeProposed,
)
from catering_system.domain.order import Order, OrderVersion
from catering_system.repositories.order_repository import OrderRepository

_log = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class OrderService:
    """Core-owned Order lifecycle: conversion (B1/B5), versions (B2), history reads (B3), candidate (B6)."""

    def __init__(
        self,
        order_repository: OrderRepository,
        *,
        event_sink: Callable[[object], None] | None = None,
    ) -> None:
        self._order_repository = order_repository
        self._event_sink = event_sink

    def _emit(self, event: object) -> None:
        if self._event_sink is not None:
            self._event_sink(event)

    def convert_inquiry_to_order(self, inquiry: Inquiry) -> tuple[Order, OrderVersion]:
        """Create Order + v1 after the Core inquiry conversion gate passes.

        Idempotent: if any Order already exists for the inquiry, return that
        Order and its initial version instead of creating another. Order
        existence is authoritative for “already converted”.
        The application command owns the accompanying Inquiry stage update.
        """
        existing = self.orders_for_inquiry(inquiry.inquiry_id)
        if existing:
            return self._existing_conversion_result(existing)

        if not inquiry_allows_order_conversion(inquiry):
            raise ValueError(
                "inquiry_to_order conversion blocked "
                f"(inquiry_id={inquiry.inquiry_id!r}, "
                f"crm_stage={inquiry.crm_stage!r}, "
                f"call_verification_required={inquiry.call_verification_required!r}, "
                f"call_verification_status={inquiry.call_verification_status!r})"
            )
        if not inquiry_contact_complete(inquiry):
            raise ValueError(
                "inquiry contact information incomplete "
                f"(inquiry_id={inquiry.inquiry_id!r})"
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
        self._order_repository.save_order_with_initial_version(order, version)
        _log.info(
            "convert_inquiry_to_order inquiry_id=%s order_id=%s version=%s",
            inquiry.inquiry_id,
            order_id,
            version.version_number,
        )
        return order, version

    def orders_for_inquiry(self, inquiry_id: str) -> list[Order]:
        return [
            order
            for order in self._order_repository.list_orders()
            if order.source_inquiry_id == inquiry_id
        ]

    def _existing_conversion_result(
        self, existing: list[Order]
    ) -> tuple[Order, OrderVersion]:
        active = [order for order in existing if order.cancelled_at is None]
        candidates = active or existing
        order = sorted(candidates, key=lambda item: (item.created_at, item.order_id))[0]
        versions = self._order_repository.list_order_versions(order.order_id)
        version = next(
            (item for item in versions if item.version_number == 1),
            None,
        )
        if version is None:
            raise ValueError(
                f"linked order {order.order_id!r} is missing initial version"
            )
        return order, version

    def create_order_from_offer_version(
        self,
        source_inquiry_id: str,
        offer_version: CommercialOfferVersion,
    ) -> tuple[Order, OrderVersion]:
        """Create Order + v1 from commercial OfferVersion facts (not Inquiry)."""
        now = _utc_now()
        order_id = str(uuid.uuid4())
        order = Order(
            order_id=order_id,
            source_inquiry_id=source_inquiry_id,
            created_at=now,
            updated_at=now,
        )
        version = OrderVersion(
            order_version_id=str(uuid.uuid4()),
            order_id=order_id,
            version_number=1,
            created_at=now,
            event_date=offer_version.event_date,
            time_window_text=offer_version.time_window_text,
            location_text=offer_version.location_text,
            guest_count_estimate=offer_version.guest_count,
            planning_mode=offer_version.planning_mode,
        )
        self._order_repository.save_order_with_initial_version(order, version)
        _log.info(
            "create_order_from_offer_version inquiry_id=%s order_id=%s version=%s",
            source_inquiry_id,
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
        if current.cancelled_at is not None:
            raise ValueError(
                f"order {order.order_id!r} is cancelled (Storno); no further versions (STORNO pack §3)"
            )
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
        self._order_repository.append_order_version(
            replace(current, updated_at=now), version
        )
        _log.info(
            "create_relevant_order_change_version order_id=%s version=%s",
            order.order_id,
            version.version_number,
        )
        return version

    def propose_order_version_change(
        self,
        order_id: str,
        *,
        event_date: date,
        time_window_text: str,
        location_text: str,
        guest_count_estimate: int | None,
        planning_mode: str,
        actor_reference: str,
        change_reason: str,
    ) -> OrderVersion:
        """Append an immutable snapshot and atomically make it current candidate.

        The parent is the effective snapshot. For an existing order that has
        never had an effective pointer, the latest stored version is used as a
        compatibility source for the initial handoff workflow.
        """
        current = self._order_repository.get_order(order_id)
        if current is None:
            raise ValueError(f"no order with id {order_id!r}")
        if current.cancelled_at is not None:
            raise ValueError(
                f"order {order_id!r} is cancelled (Storno); no further versions"
            )
        versions = self._order_repository.list_order_versions(order_id)
        if not versions:
            raise ValueError(f"order {order_id!r} has no source version")
        source = None
        if current.effective_order_version_id is not None:
            source = self._order_repository.get_order_version(
                current.effective_order_version_id
            )
            if source is None or source.order_id != order_id:
                raise ValueError("effective order version is not resolvable")
        if source is None:
            source = max(versions, key=lambda item: item.version_number)

        now = _utc_now()
        validated_planning_mode = validate_planning_mode(planning_mode)
        values: dict[str, object] = {
            "event_date": event_date,
            "time_window_text": time_window_text,
            "location_text": location_text,
            "guest_count_estimate": guest_count_estimate,
            "planning_mode": validated_planning_mode,
        }
        changed_fields = tuple(
            name for name, value in values.items() if getattr(source, name) != value
        )
        version = OrderVersion(
            order_version_id=str(uuid.uuid4()),
            order_id=order_id,
            version_number=max(item.version_number for item in versions) + 1,
            created_at=now,
            event_date=event_date,
            time_window_text=time_window_text,
            location_text=location_text,
            guest_count_estimate=guest_count_estimate,
            planning_mode=validated_planning_mode,
            parent_order_version_id=source.order_version_id,
            created_by=actor_reference,
            change_reason=change_reason,
            changed_fields=changed_fields,
        )
        previous_candidate_id = current.candidate_order_version_id
        updated = replace(
            current,
            candidate_order_version_id=version.order_version_id,
            updated_at=now,
        )
        self._order_repository.append_order_version(updated, version)
        if (
            previous_candidate_id is not None
            and previous_candidate_id != current.effective_order_version_id
        ):
            self._emit(
                OrderVersionCandidateSuperseded(
                    order_id=order_id,
                    superseded_order_version_id=previous_candidate_id,
                    new_candidate_order_version_id=version.order_version_id,
                    occurred_at=now,
                )
            )
        self._emit(
            OrderVersionChangeProposed(
                order_id=order_id,
                old_effective_order_version_id=current.effective_order_version_id,
                new_candidate_order_version_id=version.order_version_id,
                actor_reference=actor_reference,
                change_reason=change_reason,
                changed_fields=changed_fields,
                occurred_at=now,
            )
        )
        _log.info(
            "propose_order_version_change order_id=%s version=%s candidate=%s",
            order_id,
            version.version_number,
            version.order_version_id,
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

    def set_candidate_order_version(
        self, order_id: str, order_version_id: str
    ) -> Order:
        """B6: set the single office-side candidate version; does not select an effective operational version."""
        current = self._order_repository.get_order(order_id)
        if current is None:
            raise ValueError(f"no order with id {order_id!r}")
        if current.cancelled_at is not None:
            raise ValueError(
                f"order {order_id!r} is cancelled (Storno); candidate changes refused (STORNO pack §3)"
            )
        ver = self._order_repository.get_order_version(order_version_id)
        if ver is None or ver.order_id != order_id:
            raise ValueError(
                f"order_version_id {order_version_id!r} is not a version of order {order_id!r}"
            )
        now = _utc_now()
        updated = replace(
            current, candidate_order_version_id=order_version_id, updated_at=now
        )
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
