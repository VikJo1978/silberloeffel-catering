"""Unit tests — offer detail read projection (5B-2)."""

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
from catering_system.services.inquiry_service import InquiryService
from catering_system.repositories.in_memory_inquiry_repository import (
    InMemoryInquiryRepository,
)
from catering_system.ui.office_api_views import offer_detail, offer_state_label

_TODAY = date(2026, 7, 15)
_NOW = datetime(2026, 7, 15, 8, 0, tzinfo=UTC)
_OFFER_ID = "11111111-1111-4111-8111-111111111111"
_V1_ID = "33333333-3333-4333-8333-333333333331"
_V2_ID = "33333333-3333-4333-8333-333333333332"
_VARIANT_ID = "44444444-4444-4444-8444-444444444441"
_ACCEPTANCE_ID = "55555555-5555-5555-5555-555555555555"
_ORDER_ID = "66666666-6666-6666-6666-666666666666"
_HASH = "sha256:" + ("a" * 64)


def _inquiry():
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
    )


def _version(
    *,
    version_number: int = 1,
    offer_version_id: str = _V1_ID,
    valid_until: date | None = None,
    created_at: datetime | None = None,
    label: str = "Variante A",
    snapshot_id: str = "77777777-7777-4777-8777-777777777771",
) -> OfferVersion:
    return OfferVersion(
        offer_version_id=offer_version_id,
        offer_id=_OFFER_ID,
        version_number=version_number,
        created_at=created_at or _NOW,
        valid_until=valid_until or date(2026, 7, 31),
        snapshot_id=snapshot_id,
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
                offer_version_id=offer_version_id,
                label=label,
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
                sent_at=_NOW + timedelta(hours=1),
                recorded_at=_NOW + timedelta(hours=1, minutes=1),
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


def test_prepared_offer_detail_shape() -> None:
    inquiry = _inquiry()
    detail = offer_detail(_offer(inquiry.inquiry_id), today=_TODAY)
    assert detail["offer_id"] == _OFFER_ID
    assert detail["inquiry_id"] == inquiry.inquiry_id
    assert detail["commercial_state"] == "Prepared"
    assert detail["sent_evidence"] is None
    assert detail["acceptance"] is None
    assert "order_id" not in detail
    version = detail["versions"][0]
    assert version["state"] == "Prepared"
    assert version["variants"] == [
        {"variant_id": _VARIANT_ID, "name": "Variante A"}
    ]
    assert offer_state_label("Prepared") == "Vorbereitet"


def test_sent_offer_detail_includes_evidence_and_history() -> None:
    inquiry = _inquiry()
    detail = offer_detail(_offer(inquiry.inquiry_id, sent=True), today=_TODAY)
    assert detail["commercial_state"] == "Sent"
    sent = detail["sent_evidence"]
    assert sent is not None
    assert sent["channel"] == "email"
    labels = [entry["label"] for entry in detail["history"]]
    assert labels == ["Angebot erstellt", "Angebot gesendet"]


def test_accepted_offer_detail() -> None:
    inquiry = _inquiry()
    detail = offer_detail(
        _offer(inquiry.inquiry_id, sent=True, accepted=True),
        today=_TODAY,
    )
    assert detail["commercial_state"] == "Accepted"
    acceptance = detail["acceptance"]
    assert acceptance is not None
    assert acceptance["accepted_variant_id"] == _VARIANT_ID
    labels = [entry["label"] for entry in detail["history"]]
    assert "Angebot angenommen" in labels


def test_converted_offer_detail_includes_order_link() -> None:
    inquiry = _inquiry()
    detail = offer_detail(
        _offer(inquiry.inquiry_id, sent=True, accepted=True, converted=True),
        today=_TODAY,
    )
    assert detail["commercial_state"] == "Converted"
    assert detail["order_id"] == _ORDER_ID
    labels = [entry["label"] for entry in detail["history"]]
    assert labels[-1] == "In Auftrag umgewandelt"


def test_history_sorted_chronologically() -> None:
    inquiry = _inquiry()
    offer = _offer(inquiry.inquiry_id, sent=True, accepted=True, converted=True)
    history = offer_detail(offer, today=_TODAY)["history"]
    timestamps = [entry["at"] for entry in history]
    assert timestamps == sorted(timestamps)


def test_second_version_history_label() -> None:
    inquiry = _inquiry()
    offer = Offer(
        offer_id=_OFFER_ID,
        source_inquiry_id=inquiry.inquiry_id,
        created_at=_NOW,
        versions=(
            _version(version_number=1, offer_version_id=_V1_ID),
            _version(
                version_number=2,
                offer_version_id=_V2_ID,
                created_at=_NOW + timedelta(days=3),
                label="Variante B",
                snapshot_id="77777777-7777-4777-8777-777777777772",
            ),
        ),
        sent_evidence=(),
        acceptance_evidence=None,
        rejection_evidence=(),
        withdrawal_evidence=(),
        conversion_link=None,
    )
    labels = [entry["label"] for entry in offer_detail(offer, today=_TODAY)["history"]]
    assert labels == ["Angebot erstellt", "Angebot vorbereitet"]
