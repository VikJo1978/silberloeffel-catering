"""Arbeitszentrale read service — derived counters from existing Core reads."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from catering_system.domain.inquiry import (
    derive_inquiry_offer_projection,
    derive_inquiry_office_state,
)
from catering_system.domain.order import Order
from catering_system.domain.work_center import WorkCenterSnapshot
from catering_system.repositories.inquiry_repository import InquiryRepository
from catering_system.repositories.offer_repository import OfferRepository
from catering_system.repositories.order_repository import OrderRepository
from catering_system.services.calendar_projection_service import (
    CalendarProjectionService,
)
from catering_system.services.task_projection_service import TaskProjectionService
from catering_system.ui.office_api_views import berlin_today


class WorkCenterService:
    def __init__(
        self,
        inquiry_repository: InquiryRepository,
        offer_repository: OfferRepository,
        order_repository: OrderRepository,
        *,
        today: Callable[[], date] | None = None,
        missed_calls_open: Callable[[], int] | None = None,
        task_projection_service: TaskProjectionService | None = None,
        calendar_projection_service: CalendarProjectionService | None = None,
    ) -> None:
        self._inquiries = inquiry_repository
        self._offers = offer_repository
        self._orders = order_repository
        self._today = today or berlin_today
        self._missed_calls_open = missed_calls_open or (lambda: 0)
        self._tasks = task_projection_service
        self._calendar = calendar_projection_service

    def snapshot(self) -> WorkCenterSnapshot:
        operating_today = self._today()
        orders = self._orders.list_orders()
        orders_by_inquiry: dict[str, list[Order]] = {}
        for order in orders:
            orders_by_inquiry.setdefault(order.source_inquiry_id, []).append(order)

        rueckrufe_open = 0
        offers_waiting = 0
        offers_accepted = 0
        for inquiry in self._inquiries.list_all():
            linked = orders_by_inquiry.get(inquiry.inquiry_id, [])
            offer = self._offers.get_by_source_inquiry_id(inquiry.inquiry_id)
            state = derive_inquiry_office_state(
                inquiry,
                has_order=bool(linked),
                has_active_order=any(order.cancelled_at is None for order in linked),
                offer=offer,
                today=operating_today,
            )
            if state.next_action == "verify":
                rueckrufe_open += 1
            if offer is not None:
                projection = derive_inquiry_offer_projection(
                    offer, today=operating_today
                )
                commercial = projection.commercial_state
                if commercial in ("Prepared", "Sent"):
                    offers_waiting += 1
                elif commercial == "Accepted":
                    offers_accepted += 1

        upcoming_orders = 0
        pending_order_changes = 0
        for order in orders:
            if order.cancelled_at is not None:
                continue
            if (
                order.candidate_order_version_id is not None
                and order.candidate_order_version_id != order.effective_order_version_id
                and (
                    candidate := self._orders.get_order_version(
                        order.candidate_order_version_id
                    )
                )
                is not None
                and candidate.kitchen_print_confirmed_at is None
            ):
                pending_order_changes += 1
            effective_id = order.effective_order_version_id
            if effective_id is None:
                continue
            effective = self._orders.get_order_version(effective_id)
            if effective is None or effective.event_date < operating_today:
                continue
            upcoming_orders += 1

        open_tasks = len(self._tasks.list_tasks()) if self._tasks is not None else 0
        today_calendar_entries = (
            self._calendar.count_on(operating_today)
            if self._calendar is not None
            else 0
        )
        return WorkCenterSnapshot(
            rueckrufe_open=rueckrufe_open,
            missed_calls_open=self._missed_calls_open(),
            offers_waiting=offers_waiting,
            offers_accepted=offers_accepted,
            upcoming_orders=upcoming_orders,
            open_tasks=open_tasks,
            today_calendar_entries=today_calendar_entries,
            pending_order_changes=pending_order_changes,
        )
