"""Unit tests — offer list read projection (5B-1)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from catering_system.domain.offer import (
    AcceptanceEvidence,
    ConversionLink,
    Offer,
    OfferPosition,
    OfferVariant,
    OfferVersion,
    SentEvidence,
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
from catering_system.services.inquiry_service import InquiryService
from catering_system.services.work_center_service import WorkCenterService
from catering_system.ui.office_api_views import (
    offer_list_view,
    offer_state_label,
)

_TODAY = date(2026, 7, 15)
_NOW = datetime(2026, 7, 15, 8, 0, tzinfo=UTC)
_OFFER_ID = "11111111-1111-4111-8111-111111111111"
_V1_ID = "33333333-3333-4333-8333-333333333331"
_VARIANT_ID = "44444444-4444-4444-8444-444444444441"
_ACCEPTANCE_ID = "55555555-5555-5555-5555-555555555555"
_ORDER_ID = "66666666-6666-6666-6666-666666666666"
_HASH = "sha256:" + ("a" * 64)


def _inquiry(**overrides: object):
    service = InquiryService(InMemoryInquiryRepository())
    return service.create_inquiry(
        event_date=date(2026, 8, 1),
        inquiry_source="manual",
        crm_stage="Neue Anfrage",
        customer_linkage={},
        time_window_text="mittags",
        location_text="Hamburg",
        guest_count_estimate=25,
        planning_mode="caterer_suggestion",
        call_verification_required=False,
        call_verification_status="not_required",
        intake_subject="Hochzeit Müller",
        **overrides,
    )


def _version(*, valid_until: date | None = None) -> OfferVersion:
    return OfferVersion(
        offer_version_id=_V1_ID,
        offer_id=_OFFER_ID,
        version_number=1,
        created_at=_NOW,
        valid_until=valid_until or date(2026, 7, 31),
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
    )


def _offer(
    inquiry_id: str,
    *,
    sent: bool = False,
    accepted: bool = False,
    converted: bool = False,
    valid_until: date | None = None,
) -> Offer:
    sent_evidence = (
        (
            SentEvidence(
                offer_id=_OFFER_ID,
                offer_version_id=_V1_ID,
                sent_at=_NOW,
                recorded_at=_NOW + timedelta(minutes=1),
                channel="email",
                recipient_reference="kunde@example.invalid",
                evidence_reference="mail-1",
                recorded_by="office",
            ),
        )
        if sent
        else ()
    )
    acceptance = (
        AcceptanceEvidence(
            acceptance_id=_ACCEPTANCE_ID,
            offer_id=_OFFER_ID,
            accepted_offer_version_id=_V1_ID,
            accepted_variant_id=_VARIANT_ID,
            accepted_at=_NOW + timedelta(days=1),
            recorded_at=_NOW + timedelta(days=1, minutes=5),
            channel="email",
            evidence_reference="reply-1",
            recorded_by="office",
        )
        if accepted or converted
        else None
    )
    link = (
        ConversionLink(
            offer_id=_OFFER_ID,
            offer_version_id=_V1_ID,
            variant_id=_VARIANT_ID,
            acceptance_id=_ACCEPTANCE_ID,
            order_id=_ORDER_ID,
            created_at=_NOW + timedelta(days=2),
        )
        if converted
        else None
    )
    return Offer(
        offer_id=_OFFER_ID,
        source_inquiry_id=inquiry_id,
        created_at=_NOW,
        versions=(_version(valid_until=valid_until),),
        sent_evidence=sent_evidence,
        acceptance_evidence=acceptance,
        rejection_evidence=(),
        withdrawal_evidence=(),
        conversion_link=link,
    )


def test_empty_offer_list() -> None:
    assert offer_list_view([], {}) == []


def test_prepared_offer_appears_in_list() -> None:
    inquiry = _inquiry()
    offer = _offer(inquiry.inquiry_id)
    rows = offer_list_view([offer], {inquiry.inquiry_id: inquiry}, today=_TODAY)
    assert rows == [
        {
            "offer_id": _OFFER_ID,
            "inquiry_id": inquiry.inquiry_id,
            "state": "Prepared",
            "event_date": "2026-08-01",
            "valid_until": "2026-07-31",
        }
    ]
    assert offer_state_label("Prepared") == "Vorbereitet"


def test_sent_offer_appears_in_list() -> None:
    inquiry = _inquiry()
    rows = offer_list_view(
        [_offer(inquiry.inquiry_id, sent=True)],
        {inquiry.inquiry_id: inquiry},
        today=_TODAY,
    )
    assert rows[0]["state"] == "Sent"
    assert offer_state_label("Sent") == "Gesendet"


def test_accepted_offer_appears_in_list() -> None:
    inquiry = _inquiry()
    rows = offer_list_view(
        [_offer(inquiry.inquiry_id, sent=True, accepted=True)],
        {inquiry.inquiry_id: inquiry},
        today=_TODAY,
    )
    assert rows[0]["state"] == "Accepted"
    assert offer_state_label("Accepted") == "Angenommen"


def test_converted_offer_shows_converted_state() -> None:
    inquiry = _inquiry()
    rows = offer_list_view(
        [_offer(inquiry.inquiry_id, sent=True, accepted=True, converted=True)],
        {inquiry.inquiry_id: inquiry},
        today=_TODAY,
    )
    assert rows[0]["state"] == "Converted"
    assert offer_state_label("Converted") == "Auftrag erstellt"


def test_expired_offer_is_listed_but_not_counted_as_waiting() -> None:
    inquiries = InMemoryInquiryRepository()
    inquiry = InquiryService(inquiries).create_inquiry(
        event_date=date(2026, 8, 1),
        inquiry_source="manual",
        crm_stage="Neue Anfrage",
        customer_linkage={},
        time_window_text="mittags",
        location_text="Hamburg",
        guest_count_estimate=25,
        planning_mode="caterer_suggestion",
        call_verification_required=False,
        call_verification_status="not_required",
        intake_subject="Hochzeit Müller",
    )
    offers = InMemoryOfferRepository()
    offers.save(_offer(inquiry.inquiry_id, sent=True, valid_until=date(2026, 7, 10)))
    rows = offer_list_view(offers.list_all(), {inquiry.inquiry_id: inquiry}, today=_TODAY)
    assert rows[0]["state"] == "Expired"
    snapshot = WorkCenterService(
        inquiries,
        offers,
        InMemoryOrderRepository(),
        today=lambda: _TODAY,
    ).snapshot()
    assert snapshot.offers_waiting == 0
