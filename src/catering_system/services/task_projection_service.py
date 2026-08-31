"""System task projection read service — derived office actions only."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from catering_system.domain.inquiry import Inquiry, derive_inquiry_office_state
from catering_system.domain.order import Order, OrderVersion
from catering_system.domain.task_projection import (
    TaskCategory,
    TaskProjection,
    inquiry_subtitle,
    task_sort_key,
)
from catering_system.repositories.inquiry_repository import InquiryRepository
from catering_system.repositories.offer_repository import OfferRepository
from catering_system.repositories.order_repository import OrderRepository
from catering_system.services.payment_reminder_service import PaymentReminderService
from catering_system.ui.office_api_views import berlin_today, resolve_next_action


class TaskProjectionService:
    def __init__(
        self,
        inquiry_repository: InquiryRepository,
        offer_repository: OfferRepository,
        order_repository: OrderRepository,
        payment_reminder_service: PaymentReminderService,
        *,
        today: Callable[[], date] | None = None,
    ) -> None:
        self._inquiries = inquiry_repository
        self._offers = offer_repository
        self._orders = order_repository
        self._payment_reminders = payment_reminder_service
        self._today = today or berlin_today

    def list_tasks(self) -> list[TaskProjection]:
        operating_today = self._today()
        orders = self._orders.list_orders()
        orders_by_inquiry: dict[str, list[Order]] = {}
        for order in orders:
            orders_by_inquiry.setdefault(order.source_inquiry_id, []).append(order)

        tasks: list[tuple[TaskProjection, date]] = []
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
            subtitle = inquiry_subtitle(
                inquiry.intake_subject,
                inquiry.location_text,
                inquiry.inquiry_id,
            )
            if state.next_action == "verify":
                tasks.append(
                    (
                        _inquiry_task(
                            inquiry,
                            task_id=f"inquiry:{inquiry.inquiry_id}:verify",
                            category="verify",
                            title="Kundenprüfung durchführen",
                            subtitle=subtitle,
                        ),
                        inquiry.event_date,
                    )
                )
            elif state.next_action == "prepare-offer":
                tasks.append(
                    (
                        _inquiry_task(
                            inquiry,
                            task_id=f"inquiry:{inquiry.inquiry_id}:prepare-offer",
                            category="prepare_offer",
                            title="Angebot vorbereiten",
                            subtitle=subtitle,
                        ),
                        inquiry.event_date,
                    )
                )
            elif state.next_action == "prepare-next-version":
                offer_id = (
                    state.offer.offer_id
                    if state.offer is not None
                    else inquiry.inquiry_id
                )
                tasks.append(
                    (
                        TaskProjection(
                            task_id=f"offer:{offer_id}:prepare-next-version",
                            category="prepare_next_version",
                            title="Neue Angebotsversion vorbereiten",
                            subtitle=subtitle,
                            entity_type="offer",
                            entity_id=offer_id,
                            action_label="Angebot öffnen",
                            action_href=f"/offer/{offer_id}",
                            due_at=None,
                            urgency="normal",
                            opened_at=inquiry.created_at,
                        ),
                        inquiry.event_date,
                    )
                )
            elif state.next_action == "convert-accepted":
                if state.offer is None:
                    continue
                offer_id = state.offer.offer_id
                tasks.append(
                    (
                        TaskProjection(
                            task_id=f"offer:{offer_id}:convert-accepted",
                            category="convert_accepted",
                            title="Angenommenes Angebot umwandeln",
                            subtitle=subtitle,
                            entity_type="offer",
                            entity_id=offer_id,
                            action_label="Angebot öffnen",
                            action_href=f"/offer/{offer_id}",
                            due_at=None,
                            urgency="normal",
                            opened_at=inquiry.created_at,
                        ),
                        inquiry.event_date,
                    )
                )

        for order in orders:
            versions = self._orders.list_order_versions(order.order_id)
            linked_inquiry = self._inquiries.get_by_id(order.source_inquiry_id)
            subtitle = _order_subtitle(linked_inquiry, order, versions)
            event_date = _order_event_date(order, versions)

            if order.cancelled_at is None:
                next_action = resolve_next_action(order, versions)
                if next_action is not None:
                    version_id = next_action["order_version_id"]
                    if next_action["action"] == "print-confirm":
                        tasks.append(
                            (
                                TaskProjection(
                                    task_id=(
                                        f"order:{order.order_id}:print-confirm:{version_id}"
                                    ),
                                    category="order_print",
                                    title="Druck bestätigen",
                                    subtitle=subtitle,
                                    entity_type="order",
                                    entity_id=order.order_id,
                                    action_label="Auftrag öffnen",
                                    action_href=f"/order/{order.order_id}",
                                    due_at=None,
                                    urgency="normal",
                                    opened_at=order.created_at,
                                ),
                                event_date,
                            )
                        )

            try:
                payment = self._payment_reminders.view(order.order_id)
            except (KeyError, ValueError):
                continue
            if payment.next_step is None:
                continue
            due_at = payment.next_step_due_on
            overdue = due_at is not None and due_at < operating_today
            tasks.append(
                (
                    TaskProjection(
                        task_id=f"order:{order.order_id}:payment",
                        category="payment",
                        title=payment.next_step,
                        subtitle=subtitle,
                        entity_type="order",
                        entity_id=order.order_id,
                        action_label="Auftrag öffnen",
                        action_href=f"/order/{order.order_id}",
                        due_at=due_at,
                        urgency="overdue" if overdue else "normal",
                        opened_at=order.created_at,
                    ),
                    event_date,
                )
            )

        tasks.sort(key=lambda item: task_sort_key(item[0], event_date=item[1]))
        return [task for task, _event_date in tasks]


def _inquiry_task(
    inquiry: Inquiry,
    *,
    task_id: str,
    category: TaskCategory,
    title: str,
    subtitle: str,
) -> TaskProjection:
    return TaskProjection(
        task_id=task_id,
        category=category,
        title=title,
        subtitle=subtitle,
        entity_type="inquiry",
        entity_id=inquiry.inquiry_id,
        action_label="Anfrage öffnen",
        action_href=f"/inquiry/{inquiry.inquiry_id}",
        due_at=None,
        urgency="normal",
        opened_at=inquiry.created_at,
    )


def _order_event_date(order: Order, versions: list[OrderVersion]) -> date:
    target = next(
        (
            version
            for version in versions
            if version.order_version_id == order.candidate_order_version_id
        ),
        None,
    )
    if target is None and versions:
        target = max(versions, key=lambda version: version.version_number)
    if target is not None:
        return target.event_date
    return date.max


def _order_subtitle(
    inquiry: Inquiry | None,
    order: Order,
    versions: list[OrderVersion],
) -> str:
    if inquiry is not None:
        return inquiry_subtitle(
            inquiry.intake_subject,
            inquiry.location_text,
            inquiry.inquiry_id,
        )
    event_date = _order_event_date(order, versions)
    if event_date is date.max:
        return order.order_id[:8]
    return event_date.isoformat()
