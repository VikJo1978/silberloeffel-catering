from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from catering_system.domain.inquiry import Inquiry
from catering_system.domain.order import Order, OrderVersion
from catering_system.services.customer_order_history_service import (
    CustomerOrderHistoryCustomerNotFoundError,
    CustomerOrderHistoryService,
)

NOW = datetime(2026, 8, 25, 17, 0, tzinfo=UTC)


class CustomerRepo:
    def __init__(self, ids: set[str]) -> None:
        self.ids = ids

    def get_by_id(self, customer_id: str):  # noqa: ANN201
        return object() if customer_id in self.ids else None


class InquiryRepo:
    def __init__(self, inquiries: list[Inquiry]) -> None:
        self.inquiries = inquiries

    def list_all(self) -> list[Inquiry]:
        return self.inquiries


class OrderRepo:
    def __init__(
        self,
        orders: list[Order],
        versions: dict[str, list[OrderVersion]],
        contexts: dict[str, object] | None = None,
    ) -> None:
        self.orders = orders
        self.versions = versions
        self.contexts = contexts or {}

    def list_orders(self) -> list[Order]:
        return self.orders

    def list_order_versions(self, order_id: str) -> list[OrderVersion]:
        return self.versions.get(order_id, [])

    def get_operational_context(self, order_version_id: str):  # noqa: ANN201
        return self.contexts.get(order_version_id)


class OfferRepo:
    def __init__(self, offers: dict[str, object]) -> None:
        self.offers = offers

    def get_by_source_inquiry_id(self, inquiry_id: str):  # noqa: ANN201
        return self.offers.get(inquiry_id)


def _inquiry(inquiry_id: str, customer_id: str | None) -> Inquiry:
    return Inquiry(
        inquiry_id=inquiry_id,
        event_date=date(2026, 8, 20),
        created_at=NOW,
        updated_at=NOW,
        inquiry_source="manual",
        crm_stage="Bestätigt / Auftrag",
        customer_linkage={},
        time_window_text="18:00",
        location_text="Hamburg",
        guest_count_estimate=20,
        planning_mode="caterer_suggestion",
        call_verification_required=False,
        call_verification_status="not_required",
        customer_id=customer_id,
        fulfillment_mode="PICKUP",
    )


def _order(order_id: str, inquiry_id: str, *, effective: str | None = None) -> Order:
    return Order(
        order_id=order_id,
        source_inquiry_id=inquiry_id,
        created_at=NOW,
        updated_at=NOW,
        effective_order_version_id=effective,
    )


def _version(
    order_id: str,
    version_id: str,
    number: int,
    event_date: date,
    guest_count: int,
) -> OrderVersion:
    return OrderVersion(
        order_version_id=version_id,
        order_id=order_id,
        version_number=number,
        created_at=NOW,
        event_date=event_date,
        time_window_text="18:00",
        location_text="Hamburg",
        guest_count_estimate=guest_count,
        planning_mode="caterer_suggestion",
    )


def _converted_offer(order_id: str, inquiry_id: str):  # noqa: ANN202
    positions = (
        SimpleNamespace(
            position_id="dish-1",
            name="Mini-Frikadellen",
            kind="catalog",
            catalog_item_id="catalog-1",
            gross_total_cents=15000,
        ),
        SimpleNamespace(
            position_id="fee-1",
            name="Lieferung",
            kind="delivery",
            catalog_item_id=None,
            gross_total_cents=2500,
        ),
    )
    variant = SimpleNamespace(
        variant_id="variant-1",
        label="Klassik",
        positions=positions,
    )
    version = SimpleNamespace(
        offer_version_id="offer-version-1",
        variants=(variant,),
    )
    link = SimpleNamespace(
        order_id=order_id,
        offer_version_id="offer-version-1",
        variant_id="variant-1",
    )
    return SimpleNamespace(
        offer_id="offer-1",
        source_inquiry_id=inquiry_id,
        conversion_link=link,
        versions=(version,),
    )


def test_projects_only_explicitly_linked_customer_orders() -> None:
    own = _inquiry("inq-1", "customer-1")
    other = _inquiry("inq-2", "customer-2")
    order = _order("order-1", "inq-1", effective="ov-1")
    other_order = _order("order-2", "inq-2", effective="ov-2")
    service = CustomerOrderHistoryService(
        CustomerRepo({"customer-1", "customer-2"}),
        InquiryRepo([own, other]),
        OrderRepo(
            [order, other_order],
            {
                "order-1": [_version("order-1", "ov-1", 1, date(2026, 8, 20), 20)],
                "order-2": [_version("order-2", "ov-2", 1, date(2026, 8, 21), 30)],
            },
            {"ov-1": SimpleNamespace(fulfillment_mode="DELIVERY")},
        ),
        OfferRepo({"inq-1": _converted_offer("order-1", "inq-1")}),
    )

    entries = service.list_for_customer("customer-1")

    assert len(entries) == 1
    entry = entries[0]
    assert entry.order_id == "order-1"
    assert entry.event_date == date(2026, 8, 20)
    assert entry.guest_count == 20
    assert entry.fulfillment_mode == "DELIVERY"
    assert entry.accepted_variant_id == "variant-1"
    assert entry.accepted_variant_label == "Klassik"
    assert [dish.name for dish in entry.dishes] == ["Mini-Frikadellen"]
    assert entry.gross_total_cents == 17500


def test_uses_effective_version_and_sorts_most_recent_first() -> None:
    inquiry1 = _inquiry("inq-1", "customer-1")
    inquiry2 = _inquiry("inq-2", "customer-1")
    order1 = _order("order-1", "inq-1", effective="ov-1b")
    order2 = _order("order-2", "inq-2", effective="ov-2")
    service = CustomerOrderHistoryService(
        CustomerRepo({"customer-1"}),
        InquiryRepo([inquiry1, inquiry2]),
        OrderRepo(
            [order1, order2],
            {
                "order-1": [
                    _version("order-1", "ov-1a", 1, date(2026, 8, 10), 10),
                    _version("order-1", "ov-1b", 2, date(2026, 8, 30), 15),
                ],
                "order-2": [_version("order-2", "ov-2", 1, date(2026, 8, 20), 20)],
            },
        ),
        OfferRepo({}),
    )

    entries = service.list_for_customer("customer-1")

    assert [entry.order_id for entry in entries] == ["order-1", "order-2"]
    assert entries[0].order_version_id == "ov-1b"
    assert entries[0].guest_count == 15


def test_legacy_order_without_offer_trail_remains_visible() -> None:
    inquiry = _inquiry("inq-1", "customer-1")
    order = _order("order-1", "inq-1")
    service = CustomerOrderHistoryService(
        CustomerRepo({"customer-1"}),
        InquiryRepo([inquiry]),
        OrderRepo(
            [order],
            {"order-1": [_version("order-1", "ov-1", 1, date(2026, 8, 20), 20)]},
        ),
        OfferRepo({}),
    )

    [entry] = service.list_for_customer("customer-1")

    assert entry.accepted_offer_id is None
    assert entry.accepted_variant_id is None
    assert entry.dishes == ()
    assert entry.gross_total_cents is None


def test_missing_customer_is_rejected() -> None:
    service = CustomerOrderHistoryService(
        CustomerRepo(set()), InquiryRepo([]), OrderRepo([], {}), OfferRepo({})
    )

    with pytest.raises(CustomerOrderHistoryCustomerNotFoundError):
        service.list_for_customer("missing")
