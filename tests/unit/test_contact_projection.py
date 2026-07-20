"""Unit tests — contact projection read model (5C-1)."""

from __future__ import annotations

from datetime import UTC, date, datetime

from catering_system.domain.contact_projection import derive_contact_identity
from catering_system.domain.offer import (
    Offer,
    OfferPosition,
    OfferVariant,
    OfferVersion,
)
from catering_system.repositories.in_memory_inquiry_repository import (
    InMemoryInquiryRepository,
)
from catering_system.repositories.in_memory_offer_repository import (
    InMemoryOfferRepository,
)
from catering_system.repositories.in_memory_order_repository import (
    InMemoryOrderRepository,
)
from catering_system.services.contact_projection_service import ContactProjectionService
from catering_system.services.inquiry_service import InquiryService
from catering_system.services.order_service import OrderService

_TODAY = date(2026, 7, 15)
_NOW = datetime(2026, 7, 15, 8, 0, tzinfo=UTC)
_OFFER_ID = "11111111-1111-4111-8111-111111111111"
_V1_ID = "33333333-3333-4333-8333-333333333331"
_VARIANT_ID = "44444444-4444-4444-8444-444444444441"
_HASH = "sha256:" + ("a" * 64)


def _service(
    *,
    inquiries: InMemoryInquiryRepository | None = None,
    offers: InMemoryOfferRepository | None = None,
    orders: InMemoryOrderRepository | None = None,
) -> ContactProjectionService:
    return ContactProjectionService(
        inquiries or InMemoryInquiryRepository(),
        offers or InMemoryOfferRepository(),
        orders or InMemoryOrderRepository(),
        today=lambda: _TODAY,
    )


def _save_inquiry(repo: InMemoryInquiryRepository, **overrides: object):
    service = InquiryService(repo)
    payload: dict[str, object] = {
        "event_date": date(2026, 8, 1),
        "inquiry_source": "manual",
        "crm_stage": "Neue Anfrage",
        "customer_linkage": {},
        "time_window_text": "mittags",
        "location_text": "Hamburg",
        "guest_count_estimate": 25,
        "planning_mode": "caterer_suggestion",
        "call_verification_required": False,
        "call_verification_status": "not_required",
        "contact_email": "kunde@example.com",
        "contact_phone": "+49301234567",
    }
    payload.update(overrides)
    return service.create_inquiry(**payload)  # type: ignore[arg-type]


def test_empty_contacts() -> None:
    assert _service().list_contacts() == []


def test_grouping_by_customer_id() -> None:
    inquiries = InMemoryInquiryRepository()
    first = _save_inquiry(
        inquiries,
        customer_linkage={"customer_id": "cust-shared"},
        intake_subject="Firma A",
    )
    second = _save_inquiry(
        inquiries,
        customer_linkage={"customer_id": "cust-shared"},
        intake_subject="Firma B",
    )
    rows = _service(inquiries=inquiries).list_contacts()
    assert len(rows) == 1
    row = rows[0]
    assert row.contact_key == "linkage:customer:cust-shared"
    assert row.identity_source == "linkage_customer"
    assert row.inquiry_count == 2
    assert set(row.inquiry_ids) == {first.inquiry_id, second.inquiry_id}


def test_grouping_by_email() -> None:
    inquiries = InMemoryInquiryRepository()
    message = "Firma: Beispiel GmbH\nE-Mail: shared@example.invalid\n"
    _save_inquiry(inquiries, intake_message=message, intake_subject="A")
    _save_inquiry(inquiries, intake_message=message, intake_subject="B")
    rows = _service(inquiries=inquiries).list_contacts()
    assert len(rows) == 1
    assert rows[0].contact_key == "intake:email:shared@example.invalid"
    assert rows[0].identity_source == "intake_email"
    assert rows[0].email == "shared@example.invalid"
    assert rows[0].inquiry_count == 2


def test_fallback_inquiry_identity() -> None:
    inquiries = InMemoryInquiryRepository()
    inquiry = _save_inquiry(inquiries, intake_subject="Einzelanfrage")
    key, source = derive_contact_identity(inquiry)
    assert key == f"inquiry:{inquiry.inquiry_id}"
    assert source == "inquiry"
    rows = _service(inquiries=inquiries).list_contacts()
    assert len(rows) == 1
    assert rows[0].inquiry_count == 1


def test_open_inquiry_count() -> None:
    inquiries = InMemoryInquiryRepository()
    _save_inquiry(inquiries, customer_linkage={"customer_id": "cust-open"})
    rows = _service(inquiries=inquiries).list_contacts()
    assert rows[0].open_inquiries == 1
    assert rows[0].active_orders == 0


def test_open_inquiry_and_active_order_counts() -> None:
    inquiries = InMemoryInquiryRepository()
    inquiry = _save_inquiry(
        inquiries,
        customer_linkage={"customer_id": "cust-ops"},
        intake_subject="Offene Anfrage",
    )
    orders = InMemoryOrderRepository()
    order_service = OrderService(orders)
    order, _version = order_service.convert_inquiry_to_order(inquiry)
    assert order.cancelled_at is None
    rows = _service(inquiries=inquiries, orders=orders).list_contacts()
    assert rows[0].open_inquiries == 0
    assert rows[0].active_orders == 1


def test_offer_and_order_linkage_in_detail() -> None:
    inquiries = InMemoryInquiryRepository()
    inquiry = _save_inquiry(
        inquiries,
        customer_linkage={"contact_id": "ct-1"},
        intake_subject="Mit Angebot",
    )
    offers = InMemoryOfferRepository()
    offers.save(
        Offer(
            offer_id=_OFFER_ID,
            source_inquiry_id=inquiry.inquiry_id,
            created_at=_NOW,
            versions=(
                OfferVersion(
                    offer_version_id=_V1_ID,
                    offer_id=_OFFER_ID,
                    version_number=1,
                    created_at=_NOW,
                    valid_until=date(2026, 7, 31),
                    snapshot_id="77777777-7777-4777-8777-777777777771",
                    snapshot_hash=_HASH,
                    event_date=date(2026, 8, 1),
                    time_window_text="18:00–22:00",
                    location_text="Hamburg",
                    guest_count=80,
                    planning_mode="caterer_suggestion",
                    payment_method="RECHNUNG",
                    payment_customer_visible_text="Zahlung per Rechnung",
                    variants=(
                        OfferVariant(
                            variant_id=_VARIANT_ID,
                            offer_version_id=_V1_ID,
                            label="Variante A",
                            positions=(
                                OfferPosition(
                                    position_id="88888888-8888-4888-8888-888888888881",
                                    kind="catalog",
                                    name="Fingerfood Paket",
                                    unit_net_cents=290,
                                    net_total_cents=23200,
                                    vat_rate_percent=7,
                                    vat_amount_cents=1624,
                                    gross_total_cents=24824,
                                ),
                            ),
                        ),
                    ),
                ),
            ),
            sent_evidence=(),
            acceptance_evidence=None,
            rejection_evidence=(),
            withdrawal_evidence=(),
            conversion_link=None,
        )
    )
    orders = InMemoryOrderRepository()
    order, _version = OrderService(orders).convert_inquiry_to_order(inquiry)
    detail = _service(
        inquiries=inquiries,
        offers=offers,
        orders=orders,
    ).contact_detail("linkage:contact:ct-1")
    assert detail is not None
    assert len(detail.inquiries) == 1
    assert len(detail.offers) == 1
    assert detail.offers[0].offer_id == _OFFER_ID
    assert len(detail.orders) == 1
    assert detail.orders[0].order_id == order.order_id


def test_contact_detail_missing_returns_none() -> None:
    assert _service().contact_detail("inquiry:missing") is None


def test_linkage_contact_has_priority_over_email() -> None:
    inquiries = InMemoryInquiryRepository()
    inquiry = _save_inquiry(
        inquiries,
        customer_linkage={"contact_id": "ct-priority"},
        intake_message="E-Mail: other@example.invalid\n",
    )
    key, source = derive_contact_identity(inquiry)
    assert (key, source) == ("linkage:contact:ct-priority", "linkage_contact")
