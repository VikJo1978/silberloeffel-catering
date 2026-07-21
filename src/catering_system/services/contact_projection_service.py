"""Contact projection read service — aggregates inquiries/offers/orders."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime

from catering_system.domain.contact_projection import (
    ContactIdentitySource,
    ContactProjection,
    derive_contact_identity,
    derive_contact_status,
)
from catering_system.domain.inquiry import (
    Inquiry,
    derive_inquiry_office_state,
)
from catering_system.domain.offer import Offer
from catering_system.domain.order import Order
from catering_system.intake.intake_contact import parse_intake_contact
from catering_system.repositories.inquiry_repository import InquiryRepository
from catering_system.repositories.offer_repository import OfferRepository
from catering_system.repositories.order_repository import OrderRepository


@dataclass
class _ContactAccumulator:
    contact_key: str
    identity_source: ContactIdentitySource
    inquiry_ids: list[str] = field(default_factory=list)
    display_name: str = "–"
    email: str | None = None
    phone: str | None = None
    open_inquiries: int = 0
    active_order_ids: set[str] = field(default_factory=set)
    linked_order_ids: set[str] = field(default_factory=set)
    last_activity: datetime | None = None


@dataclass(frozen=True)
class ContactDetailProjection:
    contact: ContactProjection
    inquiries: tuple[Inquiry, ...]
    offers: tuple[Offer, ...]
    orders: tuple[Order, ...]


class ContactProjectionService:
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
        self._today = today or (lambda: date.today())

    def list_contacts(self) -> list[ContactProjection]:
        aggregates = self._build_aggregates()
        rows = [self._to_projection(item) for item in aggregates.values()]
        rows.sort(
            key=lambda row: (row.last_activity, row.contact_key),
            reverse=True,
        )
        return rows

    def contact_detail(self, contact_key: str) -> ContactDetailProjection | None:
        aggregates = self._build_aggregates()
        aggregate = aggregates.get(contact_key)
        if aggregate is None:
            return None
        inquiries = [
            inquiry
            for inquiry in self._inquiries.list_all()
            if inquiry.inquiry_id in aggregate.inquiry_ids
        ]
        inquiries.sort(key=lambda item: item.updated_at, reverse=True)
        inquiry_ids = {inquiry.inquiry_id for inquiry in inquiries}
        offers = [
            offer
            for offer in self._offers.list_all()
            if offer.source_inquiry_id in inquiry_ids
        ]
        offers.sort(key=lambda offer: offer.created_at, reverse=True)
        orders = [
            order
            for order in self._orders.list_orders()
            if order.source_inquiry_id in inquiry_ids
        ]
        orders.sort(key=lambda order: order.created_at, reverse=True)
        return ContactDetailProjection(
            contact=self._to_projection(aggregate),
            inquiries=tuple(inquiries),
            offers=tuple(offers),
            orders=tuple(orders),
        )

    def _build_aggregates(self) -> dict[str, _ContactAccumulator]:
        operating_today = self._today()
        orders = self._orders.list_orders()
        orders_by_inquiry: dict[str, list[Order]] = defaultdict(list)
        for order in orders:
            orders_by_inquiry[order.source_inquiry_id].append(order)

        aggregates: dict[str, _ContactAccumulator] = {}
        for inquiry in self._inquiries.list_all():
            contact_key, identity_source = derive_contact_identity(inquiry)
            aggregate = aggregates.get(contact_key)
            if aggregate is None:
                aggregate = _ContactAccumulator(
                    contact_key=contact_key,
                    identity_source=identity_source,
                )
                aggregates[contact_key] = aggregate
            aggregate.inquiry_ids.append(inquiry.inquiry_id)
            self._merge_contact_fields(aggregate, inquiry)
            linked = orders_by_inquiry.get(inquiry.inquiry_id, [])
            offer = self._offers.get_by_source_inquiry_id(inquiry.inquiry_id)
            state = derive_inquiry_office_state(
                inquiry,
                has_order=bool(linked),
                has_active_order=any(order.cancelled_at is None for order in linked),
                offer=offer,
                today=operating_today,
            )
            if state.is_open:
                aggregate.open_inquiries += 1
            for order in linked:
                aggregate.linked_order_ids.add(order.order_id)
                if order.cancelled_at is None:
                    aggregate.active_order_ids.add(order.order_id)
            activity = inquiry.updated_at
            if aggregate.last_activity is None or activity > aggregate.last_activity:
                aggregate.last_activity = activity
        return aggregates

    def _merge_contact_fields(
        self, aggregate: _ContactAccumulator, inquiry: Inquiry
    ) -> None:
        parsed = parse_intake_contact(inquiry)
        if parsed["display_name"] and aggregate.display_name == "–":
            aggregate.display_name = parsed["display_name"]
        if aggregate.email is None and parsed["email"]:
            aggregate.email = parsed["email"]
        if aggregate.phone is None and parsed["phone"]:
            aggregate.phone = parsed["phone"]
        if aggregate.display_name == "–" and inquiry.intake_subject:
            aggregate.display_name = inquiry.intake_subject.strip()

    def _to_projection(self, aggregate: _ContactAccumulator) -> ContactProjection:
        inquiry_ids = tuple(sorted(set(aggregate.inquiry_ids)))
        last_activity = aggregate.last_activity
        if last_activity is None:
            raise ValueError("contact aggregate requires last_activity")
        linked_order_count = len(aggregate.linked_order_ids)
        return ContactProjection(
            contact_key=aggregate.contact_key,
            identity_source=aggregate.identity_source,
            display_name=aggregate.display_name,
            email=aggregate.email,
            phone=aggregate.phone,
            inquiry_count=len(inquiry_ids),
            open_inquiries=aggregate.open_inquiries,
            active_orders=len(aggregate.active_order_ids),
            last_activity=last_activity,
            linked_order_count=linked_order_count,
            contact_status=derive_contact_status(linked_order_count=linked_order_count),
            inquiry_ids=inquiry_ids,
        )
