"""Unit tests — offer operational queue projection (OFFER_OPERATIONAL_QUEUE_V1)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from catering_system.domain.offer import (
    AcceptanceEvidence,
    ConversionLink,
    Offer,
    OfferPosition,
    OfferVariant,
    OfferVersion,
    RejectionEvidence,
    SentEvidence,
    WithdrawalEvidence,
)
from catering_system.repositories.in_memory_inquiry_repository import (
    InMemoryInquiryRepository,
)
from catering_system.repositories.in_memory_offer_repository import (
    InMemoryOfferRepository,
)
from catering_system.services.inquiry_service import InquiryService
from catering_system.services.offer_queue_projection_service import (
    OfferQueueProjectionService,
)

_TODAY = date(2026, 7, 15)
_NOW = datetime(2026, 7, 15, 8, 0, tzinfo=UTC)
_OFFER_ID = "11111111-1111-4111-8111-111111111111"
_OFFER_ID_B = "22222222-2222-4222-8222-222222222222"
_V1_ID = "33333333-3333-4333-8333-333333333331"
_V1_ID_B = "44444444-4444-4444-8444-444444444444"
_VARIANT_ID = "55555555-5555-5555-8555-555555555555"
_ACCEPTANCE_ID = "66666666-6666-6666-8666-666666666666"
_ORDER_ID = "77777777-7777-4777-8777-777777777771"
_HASH = "sha256:" + ("a" * 64)


def _service(
    *,
    offers: InMemoryOfferRepository | None = None,
    inquiries: InMemoryInquiryRepository | None = None,
) -> OfferQueueProjectionService:
    return OfferQueueProjectionService(
        offers or InMemoryOfferRepository(),
        inquiries or InMemoryInquiryRepository(),
        today=lambda: _TODAY,
    )


def _inquiry(**overrides: object):
    defaults = {
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
        "intake_subject": "Hochzeit Müller",
        "contact_email": "kunde@example.com",
        "contact_phone": "030 1234567",
    }
    defaults.update(overrides)
    service = InquiryService(InMemoryInquiryRepository())
    return service.create_inquiry(**defaults)  # type: ignore[arg-type]


def _version(
    *,
    offer_id: str = _OFFER_ID,
    version_id: str = _V1_ID,
    valid_until: date | None = None,
    created_at: datetime | None = None,
) -> OfferVersion:
    return OfferVersion(
        offer_version_id=version_id,
        offer_id=offer_id,
        version_number=1,
        created_at=created_at or _NOW,
        valid_until=valid_until or date(2026, 7, 31),
        snapshot_id="88888888-8888-4888-8888-888888888881",
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
                offer_version_id=version_id,
                label="Variante A",
                positions=(
                    OfferPosition(
                        position_id="99999999-9999-4999-8999-999999999991",
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
    offer_id: str = _OFFER_ID,
    version_id: str = _V1_ID,
    sent: bool = False,
    accepted: bool = False,
    converted: bool = False,
    valid_until: date | None = None,
    created_at: datetime | None = None,
) -> Offer:
    sent_evidence = (
        (
            SentEvidence(
                offer_id=offer_id,
                offer_version_id=version_id,
                sent_at=created_at or _NOW,
                recorded_at=(created_at or _NOW) + timedelta(minutes=1),
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
            offer_id=offer_id,
            accepted_offer_version_id=version_id,
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
            offer_id=offer_id,
            offer_version_id=version_id,
            variant_id=_VARIANT_ID,
            acceptance_id=_ACCEPTANCE_ID,
            order_id=_ORDER_ID,
            created_at=_NOW + timedelta(days=2),
        )
        if converted
        else None
    )
    return Offer(
        offer_id=offer_id,
        source_inquiry_id=inquiry_id,
        created_at=created_at or _NOW,
        versions=(_version(offer_id=offer_id, version_id=version_id, valid_until=valid_until, created_at=created_at),),
        sent_evidence=sent_evidence,
        acceptance_evidence=acceptance,
        rejection_evidence=(),
        withdrawal_evidence=(),
        conversion_link=link,
    )


def _section(snapshot, group: str):
    for section in snapshot.sections:
        if section.group == group:
            return section
    raise AssertionError(f"missing section {group!r}")


def test_empty_queue_snapshot() -> None:
    snapshot = _service().snapshot()
    assert snapshot.total_count == 0
    assert len(snapshot.sections) == 3
    assert all(section.count == 0 for section in snapshot.sections)


def test_prepared_in_action_required() -> None:
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
        contact_email="kunde@example.com",
        contact_phone="030 1234567",
    )
    offers = InMemoryOfferRepository()
    offers.save(_offer(inquiry.inquiry_id))
    item = _section(_service(offers=offers, inquiries=inquiries).snapshot(), "action_required").items[0]
    assert item.queue_subkind == "prepared"
    assert item.next_action == "mark_sent"
    assert item.next_action_label == "Als gesendet markieren"


def test_sent_expires_today_stays_sent_with_hint() -> None:
    inquiry = _inquiry()
    offers = InMemoryOfferRepository()
    offers.save(
        _offer(
            inquiry.inquiry_id,
            sent=True,
            valid_until=_TODAY,
        )
    )
    inquiries = InMemoryInquiryRepository()
    inquiries.save(inquiry)
    item = _section(_service(offers=offers, inquiries=inquiries).snapshot(), "action_required").items[0]
    assert item.state == "Sent"
    assert item.validity_hint == "expires_today"
    assert item.next_action_label == "Läuft heute ab"


def test_expired_in_overdue_without_action_button() -> None:
    inquiry = _inquiry()
    offers = InMemoryOfferRepository()
    offers.save(
        _offer(
            inquiry.inquiry_id,
            sent=True,
            valid_until=date(2026, 7, 10),
        )
    )
    inquiries = InMemoryInquiryRepository()
    inquiries.save(inquiry)
    item = _section(_service(offers=offers, inquiries=inquiries).snapshot(), "overdue").items[0]
    assert item.state == "Expired"
    assert item.next_action == "none"
    assert item.next_action_label == "Frist abgelaufen"
    assert item.days_overdue == 5


def test_accepted_with_incomplete_contact_is_blocked() -> None:
    inquiry = _inquiry(contact_email=None, contact_phone=None)
    offers = InMemoryOfferRepository()
    offers.save(_offer(inquiry.inquiry_id, sent=True, accepted=True))
    inquiries = InMemoryInquiryRepository()
    inquiries.save(inquiry)
    item = _section(_service(offers=offers, inquiries=inquiries).snapshot(), "action_required").items[0]
    assert item.queue_subkind == "accepted_contact_blocked"
    assert item.next_action == "complete_contact"
    assert item.next_action_label == "Kontaktdaten vervollständigen"


def test_converted_offer_in_history() -> None:
    inquiry = _inquiry()
    offers = InMemoryOfferRepository()
    offers.save(_offer(inquiry.inquiry_id, sent=True, accepted=True, converted=True))
    inquiries = InMemoryInquiryRepository()
    inquiries.save(inquiry)
    snapshot = _service(offers=offers, inquiries=inquiries).snapshot()
    assert _section(snapshot, "action_required").count == 0
    assert _section(snapshot, "overdue").count == 0
    assert _section(snapshot, "history").items[0].queue_subkind == "converted"


def test_rejected_inquiry_excluded_from_active_queue_but_in_history() -> None:
    inquiry = _inquiry(crm_stage="Abgelehnt / verloren")
    offers = InMemoryOfferRepository()
    offers.save(_offer(inquiry.inquiry_id, sent=True))
    inquiries = InMemoryInquiryRepository()
    inquiries.save(inquiry)
    snapshot = _service(offers=offers, inquiries=inquiries).snapshot()
    assert _section(snapshot, "action_required").count == 0
    assert _section(snapshot, "overdue").count == 0
    assert _section(snapshot, "history").items[0].queue_subkind == "inquiry_closed"


def test_prepared_sorted_before_sent() -> None:
    inquiry_a = _inquiry(intake_subject="A")
    inquiry_b = _inquiry(intake_subject="B")
    prepared_at = _NOW
    sent_at = _NOW + timedelta(hours=1)
    offers = InMemoryOfferRepository()
    offers.save(
        _offer(
            inquiry_a.inquiry_id,
            offer_id=_OFFER_ID,
            version_id=_V1_ID,
            sent=True,
            created_at=sent_at,
        )
    )
    offers.save(
        _offer(
            inquiry_b.inquiry_id,
            offer_id=_OFFER_ID_B,
            version_id=_V1_ID_B,
            created_at=prepared_at,
        )
    )
    inquiries = InMemoryInquiryRepository()
    inquiries.save(inquiry_a)
    inquiries.save(inquiry_b)
    items = _section(
        _service(offers=offers, inquiries=inquiries).snapshot(), "action_required"
    ).items
    assert [item.queue_subkind for item in items] == ["prepared", "sent"]


def test_group_filter_limits_sections() -> None:
    inquiry = _inquiry()
    offers = InMemoryOfferRepository()
    offers.save(_offer(inquiry.inquiry_id, sent=True, accepted=True, converted=True))
    inquiries = InMemoryInquiryRepository()
    inquiries.save(inquiry)
    snapshot = _service(offers=offers, inquiries=inquiries).snapshot(group="history")
    assert len(snapshot.sections) == 1
    assert snapshot.sections[0].group == "history"
    assert snapshot.total_count == 1


def test_accepted_with_complete_contact_can_convert() -> None:
    inquiry = _inquiry()
    offers = InMemoryOfferRepository()
    offers.save(_offer(inquiry.inquiry_id, sent=True, accepted=True))
    inquiries = InMemoryInquiryRepository()
    inquiries.save(inquiry)
    item = _section(_service(offers=offers, inquiries=inquiries).snapshot(), "action_required").items[0]
    assert item.queue_subkind == "accepted"
    assert item.next_action == "convert_accepted"
    assert item.next_action_label == "In Auftrag umwandeln"


def test_customer_display_uses_location_when_no_snapshot() -> None:
    inquiry = _inquiry(intake_subject=None, contact_email="a@b.c", contact_phone="1")
    offers = InMemoryOfferRepository()
    offers.save(_offer(inquiry.inquiry_id))
    inquiries = InMemoryInquiryRepository()
    inquiries.save(inquiry)
    item = _section(_service(offers=offers, inquiries=inquiries).snapshot(), "action_required").items[0]
    assert item.customer_display == "Hamburg"


def test_skips_offer_without_matching_inquiry() -> None:
    offers = InMemoryOfferRepository()
    offers.save(_offer("missing-inquiry-id"))
    snapshot = _service(offers=offers).snapshot()
    assert snapshot.total_count == 0


def test_rejected_offer_in_history() -> None:
    inquiry = _inquiry()
    offers = InMemoryOfferRepository()
    offer = _offer(inquiry.inquiry_id, sent=True)
    rejected = Offer(
        offer_id=offer.offer_id,
        source_inquiry_id=offer.source_inquiry_id,
        created_at=offer.created_at,
        versions=offer.versions,
        sent_evidence=offer.sent_evidence,
        acceptance_evidence=None,
        rejection_evidence=(
            RejectionEvidence(
                offer_id=offer.offer_id,
                offer_version_id=_V1_ID,
                rejected_at=_NOW + timedelta(days=2),
                recorded_at=_NOW + timedelta(days=2, minutes=1),
                recorded_by="office",
                evidence_reference="reject-1",
            ),
        ),
        withdrawal_evidence=(),
        conversion_link=None,
    )
    offers.save(rejected)
    inquiries = InMemoryInquiryRepository()
    inquiries.save(inquiry)
    item = _section(_service(offers=offers, inquiries=inquiries).snapshot(), "history").items[0]
    assert item.queue_subkind == "rejected"
    assert item.next_action == "none"


def test_withdrawn_offer_in_history() -> None:
    inquiry = _inquiry()
    offers = InMemoryOfferRepository()
    offer = _offer(inquiry.inquiry_id, sent=True)
    withdrawn = Offer(
        offer_id=offer.offer_id,
        source_inquiry_id=offer.source_inquiry_id,
        created_at=offer.created_at,
        versions=offer.versions,
        sent_evidence=offer.sent_evidence,
        acceptance_evidence=None,
        rejection_evidence=(),
        withdrawal_evidence=(
            WithdrawalEvidence(
                offer_id=offer.offer_id,
                offer_version_id=_V1_ID,
                withdrawn_at=_NOW + timedelta(days=2),
                recorded_by="office",
                reason="Kunde nicht erreichbar",
            ),
        ),
        conversion_link=None,
    )
    offers.save(withdrawn)
    inquiries = InMemoryInquiryRepository()
    inquiries.save(inquiry)
    item = _section(_service(offers=offers, inquiries=inquiries).snapshot(), "history").items[0]
    assert item.queue_subkind == "withdrawn"
