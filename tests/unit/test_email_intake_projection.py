"""Unit tests — email intake projection read model (5C-2)."""

from __future__ import annotations

from datetime import UTC, date, datetime

from catering_system.domain.email_intake_projection import (
    email_intake_preview,
    email_intake_subject,
    project_email_intake,
)
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
from catering_system.services.email_intake_projection_service import (
    EmailIntakeProjectionService,
)
from catering_system.services.inquiry_service import InquiryService
from catering_system.services.order_service import OrderService

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
) -> EmailIntakeProjectionService:
    return EmailIntakeProjectionService(
        inquiries or InMemoryInquiryRepository(),
        offers or InMemoryOfferRepository(),
        orders or InMemoryOrderRepository(),
    )


def _save_inquiry(repo: InMemoryInquiryRepository, **overrides: object):
    service = InquiryService(repo)
    payload: dict[str, object] = {
        "event_date": date(2026, 8, 1),
        "inquiry_source": "email",
        "crm_stage": "Neue Anfrage",
        "customer_linkage": {},
        "time_window_text": "abends",
        "location_text": "Hamburg",
        "guest_count_estimate": 25,
        "planning_mode": "caterer_suggestion",
        "call_verification_required": True,
        "call_verification_status": "pending",
        "contact_email": "kunde@example.com",
        "contact_phone": "+49301234567",
    }
    payload.update(overrides)
    return service.create_inquiry(**payload)  # type: ignore[arg-type]


def test_subject_prefers_intake_subject() -> None:
    inquiry = _save_inquiry(
        InMemoryInquiryRepository(),
        intake_subject="Catering Anfrage",
        location_text="Fallback Ort",
    )
    assert email_intake_subject(inquiry) == "Catering Anfrage"


def test_subject_falls_back_to_location_text() -> None:
    inquiry = _save_inquiry(
        InMemoryInquiryRepository(),
        location_text="Betreff aus Ort",
    )
    assert email_intake_subject(inquiry) == "Betreff aus Ort"


def test_subject_falls_back_to_ohne_betreff() -> None:
    inquiry = _save_inquiry(
        InMemoryInquiryRepository(),
        location_text="",
        intake_subject="",
    )
    assert email_intake_subject(inquiry) == "Ohne Betreff"


def test_preview_prefers_intake_message() -> None:
    inquiry = _save_inquiry(
        InMemoryInquiryRepository(),
        intake_message="Hallo, wir planen ein Event.",
        time_window_text="abends",
    )
    assert email_intake_preview(inquiry) == "Hallo, wir planen ein Event."


def test_preview_falls_back_to_time_window_text() -> None:
    inquiry = _save_inquiry(
        InMemoryInquiryRepository(),
        time_window_text="18:00–22:00",
    )
    assert email_intake_preview(inquiry) == "18:00–22:00"


def test_preview_empty_when_no_message_fields() -> None:
    inquiry = _save_inquiry(
        InMemoryInquiryRepository(),
        intake_message="",
        time_window_text="",
    )
    assert email_intake_preview(inquiry) == ""


def test_sender_email_from_intake_message() -> None:
    inquiries = InMemoryInquiryRepository()
    inquiry = _save_inquiry(
        inquiries,
        intake_message="Firma: Test GmbH\nE-Mail: sender@example.invalid\n",
    )
    row = project_email_intake(inquiry, offer=None, orders=[])
    assert row.sender_email == "sender@example.invalid"
    assert row.email_id == inquiry.inquiry_id
    assert row.inquiry_id == inquiry.inquiry_id


def test_list_emails_filters_email_source_only() -> None:
    inquiries = InMemoryInquiryRepository()
    email_inquiry = _save_inquiry(inquiries, intake_subject="E-Mail Anfrage")
    manual = InquiryService(inquiries).create_inquiry(
        event_date=date(2026, 8, 2),
        inquiry_source="manual",
        crm_stage="Neue Anfrage",
        customer_linkage={},
        time_window_text="mittags",
        location_text="Kiel",
        guest_count_estimate=10,
        planning_mode="caterer_suggestion",
        call_verification_required=False,
        call_verification_status="not_required",
    )
    website = InquiryService(inquiries).create_inquiry(
        event_date=date(2026, 8, 3),
        inquiry_source="website_form",
        crm_stage="Neue Anfrage",
        customer_linkage={},
        time_window_text="mittags",
        location_text="Kiel",
        guest_count_estimate=10,
        planning_mode="caterer_suggestion",
        call_verification_required=True,
        call_verification_status="pending",
        contact_email="kunde@example.com",
        contact_phone="+49301234567",
    )
    rows = _service(inquiries=inquiries).list_emails()
    assert len(rows) == 1
    assert rows[0].inquiry_id == email_inquiry.inquiry_id
    assert manual.inquiry_id not in {row.inquiry_id for row in rows}
    assert website.inquiry_id not in {row.inquiry_id for row in rows}


def test_offer_and_order_linkage() -> None:
    inquiries = InMemoryInquiryRepository()
    inquiry = _save_inquiry(
        inquiries,
        intake_subject="Mit Verknüpfungen",
        call_verification_required=False,
        call_verification_status="not_required",
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
    row = _service(inquiries=inquiries, offers=offers, orders=orders).email_detail(
        inquiry.inquiry_id
    )
    assert row is not None
    assert row.linked_offer_id == _OFFER_ID
    assert row.linked_order_ids == (order.order_id,)


def test_email_detail_missing_or_non_email_returns_none() -> None:
    inquiries = InMemoryInquiryRepository()
    manual = InquiryService(inquiries).create_inquiry(
        event_date=date(2026, 8, 1),
        inquiry_source="manual",
        crm_stage="Neue Anfrage",
        customer_linkage={},
        time_window_text="mittags",
        location_text="Kiel",
        guest_count_estimate=10,
        planning_mode="caterer_suggestion",
        call_verification_required=False,
        call_verification_status="not_required",
    )
    service = _service(inquiries=inquiries)
    assert service.email_detail("missing-id") is None
    assert service.email_detail(manual.inquiry_id) is None
