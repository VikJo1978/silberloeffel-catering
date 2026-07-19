"""Event calendar projection read service — one entry per source inquiry."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from catering_system.domain.calendar_entry_projection import (
    CalendarEntryKind,
    CalendarEntryProjection,
    calendar_sort_key,
    calendar_title,
)
from catering_system.domain.inquiry import Inquiry
from catering_system.domain.offer import Offer, OfferVersion, derive_offer_state
from catering_system.domain.order import Order, OrderVersion
from catering_system.repositories.inquiry_repository import InquiryRepository
from catering_system.repositories.offer_repository import OfferRepository
from catering_system.repositories.order_repository import OrderRepository
from catering_system.ui.office_api_views import berlin_today


class CalendarProjectionService:
    def __init__(
        self,
        inquiry_repository: InquiryRepository,
        offer_repository: OfferRepository,
        order_repository: OrderRepository,
        *,
        today: Callable[[], date] | None = None,
    ) -> None:
        self._inquiries = inquiry_repository
        self._offers = offer_repository
        self._orders = order_repository
        self._today = today or berlin_today

    def list_entries(
        self,
        from_date: date,
        to_date: date,
    ) -> list[CalendarEntryProjection]:
        if from_date > to_date:
            raise ValueError("from_date must not be after to_date")
        operating_today = self._today()
        orders_by_inquiry: dict[str, list[Order]] = {}
        for order in self._orders.list_orders():
            orders_by_inquiry.setdefault(order.source_inquiry_id, []).append(order)

        entries: list[CalendarEntryProjection] = []
        for inquiry in self._inquiries.list_all():
            linked = orders_by_inquiry.get(inquiry.inquiry_id, [])
            entry = self._project_inquiry(
                inquiry,
                linked,
                offer=self._offers.get_by_source_inquiry_id(inquiry.inquiry_id),
                today=operating_today,
            )
            if entry is None:
                continue
            if from_date <= entry.event_date <= to_date:
                entries.append(entry)
        entries.sort(key=calendar_sort_key)
        return entries

    def count_on(self, event_date: date) -> int:
        return len(self.list_entries(event_date, event_date))

    def _project_inquiry(
        self,
        inquiry: Inquiry,
        linked_orders: list[Order],
        *,
        offer: Offer | None,
        today: date,
    ) -> CalendarEntryProjection | None:
        active_orders = [order for order in linked_orders if order.cancelled_at is None]
        if active_orders:
            order = active_orders[0]
            versions = self._orders.list_order_versions(order.order_id)
            if order.effective_order_version_id is not None:
                effective = self._orders.get_order_version(
                    order.effective_order_version_id
                )
                if effective is not None and effective.order_id == order.order_id:
                    return self._order_entry(
                        inquiry,
                        order,
                        effective,
                        entry_kind="event_confirmed",
                    )
            target = self._target_order_version(order, versions)
            if target is None:
                return None
            return self._order_entry(
                inquiry,
                order,
                target,
                entry_kind="event_planned",
            )

        if any(order.cancelled_at is not None for order in linked_orders):
            return None

        if offer is not None and self._offer_calendar_eligible(offer, today=today):
            version = _latest_offer_version(offer)
            return self._offer_entry(inquiry, offer, version)

        if not _inquiry_calendar_relevant(inquiry):
            return None
        return self._inquiry_entry(inquiry)

    def _offer_calendar_eligible(self, offer: Offer, *, today: date) -> bool:
        version = _latest_offer_version(offer)
        state = derive_offer_state(offer, version.offer_version_id, today=today)
        return state in ("Prepared", "Sent", "Accepted")

    def _order_entry(
        self,
        inquiry: Inquiry,
        order: Order,
        version: OrderVersion,
        *,
        entry_kind: CalendarEntryKind,
    ) -> CalendarEntryProjection:
        return CalendarEntryProjection(
            entry_id=f"order:{order.order_id}:event",
            entry_kind=entry_kind,
            title=calendar_title(
                inquiry.intake_subject,
                version.location_text or inquiry.location_text,
                inquiry.inquiry_id,
            ),
            event_date=version.event_date,
            time_window_text=version.time_window_text,
            location_text=version.location_text,
            guest_count_estimate=version.guest_count_estimate,
            entity_type="order",
            entity_id=order.order_id,
            action_label="Auftrag öffnen",
            action_href=f"/order/{order.order_id}",
            source_inquiry_id=inquiry.inquiry_id,
        )

    def _offer_entry(
        self,
        inquiry: Inquiry,
        offer: Offer,
        version: OfferVersion,
    ) -> CalendarEntryProjection:
        return CalendarEntryProjection(
            entry_id=f"offer:{offer.offer_id}:event",
            entry_kind="event_tentative",
            title=calendar_title(
                inquiry.intake_subject,
                version.location_text or inquiry.location_text,
                inquiry.inquiry_id,
            ),
            event_date=version.event_date,
            time_window_text=version.time_window_text,
            location_text=version.location_text,
            guest_count_estimate=version.guest_count,
            entity_type="offer",
            entity_id=offer.offer_id,
            action_label="Angebot öffnen",
            action_href=f"/offer/{offer.offer_id}",
            source_inquiry_id=inquiry.inquiry_id,
        )

    def _inquiry_entry(self, inquiry: Inquiry) -> CalendarEntryProjection:
        return CalendarEntryProjection(
            entry_id=f"inquiry:{inquiry.inquiry_id}:event",
            entry_kind="event_tentative",
            title=calendar_title(
                inquiry.intake_subject,
                inquiry.location_text,
                inquiry.inquiry_id,
            ),
            event_date=inquiry.event_date,
            time_window_text=inquiry.time_window_text,
            location_text=inquiry.location_text,
            guest_count_estimate=inquiry.guest_count_estimate,
            entity_type="inquiry",
            entity_id=inquiry.inquiry_id,
            action_label="Anfrage öffnen",
            action_href=f"/inquiry/{inquiry.inquiry_id}",
            source_inquiry_id=inquiry.inquiry_id,
        )

    @staticmethod
    def _target_order_version(
        order: Order, versions: list[OrderVersion]
    ) -> OrderVersion | None:
        if not versions:
            return None
        target = next(
            (
                version
                for version in versions
                if version.order_version_id == order.candidate_order_version_id
            ),
            None,
        )
        if target is None:
            target = max(versions, key=lambda version: version.version_number)
        return target


def _latest_offer_version(offer: Offer) -> OfferVersion:
    return max(offer.versions, key=lambda version: version.version_number)


def _inquiry_calendar_relevant(inquiry: Inquiry) -> bool:
    return inquiry.crm_stage != "Abgelehnt / verloren"
