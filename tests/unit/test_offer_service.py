"""Unit tests — OfferService.prepare_offer_version (Slice 1B)."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from catering_system.domain.inquiry import (
    CALL_VERIFICATION_STATUSES,
    CRM_PIPELINE,
    Inquiry,
    PLANNING_MODES,
)
from catering_system.domain.offer import (
    AcceptanceEvidence,
    ConversionLink,
    Offer,
    OfferPosition,
    OfferVariant,
    OfferVersion,
    SentEvidence,
    WithdrawalEvidence,
    derive_offer_state,
)
from catering_system.domain.order import Order, OrderVersion
from catering_system.domain.offer_snapshot import compute_snapshot_hash
from catering_system.repositories.in_memory_inquiry_repository import (
    InMemoryInquiryRepository,
)
from catering_system.repositories.in_memory_offer_repository import (
    InMemoryOfferRepository,
)
from catering_system.repositories.in_memory_order_repository import (
    InMemoryOrderRepository,
)
from catering_system.services.offer_service import OfferService
from catering_system.services.operational_core_service import OperationalCoreService
from catering_system.services.order_service import OrderService

_INQUIRY_ID = "22222222-2222-4222-8222-222222222222"
_SNAPSHOT_ID = "77777777-7777-4777-8777-777777777771"
_VARIANT_ID = "44444444-4444-4444-8444-444444444441"
_POSITION_ID = "88888888-8888-4888-8888-888888888881"
_NOW = datetime(2026, 7, 15, 8, 30, tzinfo=UTC)
_SENT_AT = datetime(2026, 7, 15, 10, 0, tzinfo=UTC)
_RECORDED_AT = datetime(2026, 7, 15, 10, 0, 5, tzinfo=UTC)
_HASH = "sha256:" + ("a" * 64)
_EVENT_DATE = date(2026, 8, 20)


def _version_facts(**overrides: object) -> dict[str, object]:
    facts: dict[str, object] = {
        "event_date": _EVENT_DATE,
        "time_window_text": "18:00–22:00",
        "location_text": "Hamburg",
        "guest_count": 80,
        "planning_mode": "caterer_suggestion",
        "payment_method": "RECHNUNG",
        "payment_customer_visible_text": "Zahlung per Rechnung",
    }
    facts.update(overrides)
    return facts


def _position() -> dict[str, object]:
    return {
        "position_id": _POSITION_ID,
        "kind": "catalog",
        "catalog_item_id": "catalog-1",
        "name": "Fingerfood Paket",
        "description": "Frozen description",
        "composition": "Frozen composition",
        "quantity_mode": "total",
        "quantity": "80",
        "unit_label": "Stück",
        "unit_net_cents": 290,
        "net_total_cents": 23200,
        "vat_rate_percent": 7,
        "vat_amount_cents": 1624,
        "gross_total_cents": 24824,
        "notes": "Frozen customization",
        "related_position_id": None,
    }


def _variant() -> dict[str, object]:
    return {
        "variant_id": _VARIANT_ID,
        "label": "Variante A",
        "description": "Customer-visible alternative",
        "positions": [_position()],
        "totals": {
            "net_cents": 23200,
            "vat_7_base_cents": 23200,
            "vat_7_amount_cents": 1624,
            "vat_19_base_cents": 0,
            "vat_19_amount_cents": 0,
            "gross_cents": 24824,
        },
    }


def _valid_snapshot(*, inquiry_id: str = _INQUIRY_ID) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "offer_snapshot_v1",
        "source": "fingerfood-configurator-backend",
        "source_draft_id": "draft-1",
        "inquiry_id": inquiry_id,
        "snapshot_id": _SNAPSHOT_ID,
        "snapshot_created_at": "2026-07-15T08:30:00+00:00",
        "valid_until": "2026-07-29",
        "currency": "EUR",
        "recipient": {
            "company_name": "Example company",
            "contact_name": "Example contact",
            "email": "customer@example.invalid",
            "postal_address": "Customer-visible recipient address",
        },
        "event": {
            "event_date": "2026-08-20",
            "time_window_text": "18:00–22:00",
            "location_text": "Hamburg",
            "guest_count": 80,
            "planning_mode": "caterer_suggestion",
        },
        "customer_text": {
            "title": "Sommerfest",
            "introduction": "Customer-visible introduction",
            "notes": "Customer-visible conditions and notes",
        },
        "payment_terms": {
            "method": "RECHNUNG",
            "customer_visible_text": "Zahlung per Rechnung",
        },
        "calculator": {
            "name": "fingerfood-backend",
            "calculator_revision": "future-revision",
            "catalog_revision": "future-revision",
            "tax_revision": "future-revision",
        },
        "variants": [_variant()],
    }
    payload["snapshot_hash"] = compute_snapshot_hash(payload)
    return payload


def _sample_inquiry(*, inquiry_id: str = _INQUIRY_ID) -> Inquiry:
    return Inquiry(
        inquiry_id=inquiry_id,
        event_date=date(2026, 8, 20),
        created_at=_NOW,
        updated_at=_NOW,
        inquiry_source="manual",
        crm_stage=CRM_PIPELINE[0],
        customer_linkage={},
        time_window_text="18:00–22:00",
        location_text="Hamburg",
        guest_count_estimate=80,
        planning_mode=PLANNING_MODES[0],
        call_verification_required=False,
        call_verification_status=CALL_VERIFICATION_STATUSES[0],
    )


class _CountingOfferRepository(InMemoryOfferRepository):
    def __init__(self) -> None:
        super().__init__()
        self.save_calls = 0

    def save(self, offer: Offer) -> None:
        self.save_calls += 1
        super().save(offer)


class _FailingOfferRepository(InMemoryOfferRepository):
    def __init__(self, error: Exception) -> None:
        super().__init__()
        self._error = error
        self.save_calls = 0

    def save(self, offer: Offer) -> None:
        self.save_calls += 1
        raise self._error


class _FailingAppendRepository(InMemoryOfferRepository):
    def __init__(self, error: Exception) -> None:
        super().__init__()
        self._error = error
        self.append_calls = 0

    def append_sent_evidence(self, evidence: SentEvidence) -> Offer:
        self.append_calls += 1
        raise self._error

    def append_acceptance_evidence(self, evidence: AcceptanceEvidence) -> Offer:
        self.append_calls += 1
        raise self._error


class _FailingConversionAppendRepository(InMemoryOfferRepository):
    def __init__(self, error: Exception) -> None:
        super().__init__()
        self._error = error
        self.append_calls = 0

    def append_conversion_link(self, link: ConversionLink) -> Offer:
        self.append_calls += 1
        raise self._error


def _existing_offer(*, inquiry_id: str = _INQUIRY_ID) -> Offer:
    version_id = "33333333-3333-4333-8333-333333333333"
    return Offer(
        offer_id="11111111-1111-4111-8111-111111111111",
        source_inquiry_id=inquiry_id,
        created_at=_NOW,
        versions=(
            OfferVersion(
                offer_version_id=version_id,
                offer_id="11111111-1111-4111-8111-111111111111",
                version_number=1,
                created_at=_NOW,
                valid_until=date(2026, 7, 29),
                snapshot_id="99999999-9999-4999-8999-999999999991",
                snapshot_hash=_HASH,
                **_version_facts(),
                variants=(
                    OfferVariant(
                        variant_id=_VARIANT_ID,
                        offer_version_id=version_id,
                        label="Existing",
                        positions=(
                            OfferPosition(
                                position_id=_POSITION_ID,
                                kind="catalog",
                                name="Existing position",
                                unit_net_cents=100,
                                net_total_cents=100,
                                vat_rate_percent=7,
                                vat_amount_cents=7,
                                gross_total_cents=107,
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )


def _world(
    *,
    inquiry: Inquiry | None = None,
    offers: InMemoryOfferRepository | None = None,
) -> tuple[
    InMemoryInquiryRepository,
    InMemoryOrderRepository,
    InMemoryOfferRepository,
    OfferService,
]:
    inquiries = InMemoryInquiryRepository()
    orders = InMemoryOrderRepository()
    offer_repo = offers or InMemoryOfferRepository()
    if inquiry is not None:
        inquiries.save(inquiry)
    service = OfferService(offer_repo, inquiries, orders)
    return inquiries, orders, offer_repo, service


def test_prepare_offer_version_happy_path() -> None:
    offers = _CountingOfferRepository()
    _inquiries, _orders, _offers, service = _world(
        inquiry=_sample_inquiry(), offers=offers
    )
    payload = _valid_snapshot()

    offer = service.prepare_offer_version(_INQUIRY_ID, payload)

    assert offers.save_calls == 1
    assert offer.source_inquiry_id == _INQUIRY_ID
    assert len(offer.versions) == 1
    version = offer.versions[0]
    assert version.version_number == 1
    assert version.snapshot_id == _SNAPSHOT_ID
    assert version.snapshot_hash == payload["snapshot_hash"]
    assert version.valid_until == date(2026, 7, 29)
    assert version.created_at == _NOW
    assert offer.created_at == _NOW
    assert len(version.variants) == 1
    assert version.variants[0].variant_id == _VARIANT_ID
    assert version.variants[0].label == "Variante A"
    position = version.variants[0].positions[0]
    assert position.position_id == _POSITION_ID
    assert position.name == "Fingerfood Paket"
    assert position.unit_net_cents == 290
    assert position.description == "Frozen description"
    assert position.composition == "Frozen composition"
    assert position.notes == "Frozen customization"
    assert position.quantity == Decimal("80")
    assert position.quantity_mode == "total"
    assert position.unit_label == "Stück"
    assert version.variants[0].description == "Customer-visible alternative"
    stored = offers.get(offer.offer_id)
    assert stored == offer
    assert offers.get_by_source_inquiry_id(_INQUIRY_ID) == offer


def test_prepare_offer_version_missing_inquiry() -> None:
    offers = _CountingOfferRepository()
    _inquiries, _orders, _offers, service = _world(offers=offers)

    with pytest.raises(KeyError, match=_INQUIRY_ID):
        service.prepare_offer_version(_INQUIRY_ID, _valid_snapshot())

    assert offers.save_calls == 0
    assert offers.get_by_source_inquiry_id(_INQUIRY_ID) is None


def test_prepare_offer_version_inquiry_mismatch() -> None:
    offers = _CountingOfferRepository()
    _inquiries, _orders, _offers, service = _world(
        inquiry=_sample_inquiry(), offers=offers
    )
    other_id = "33333333-3333-4333-8333-333333333333"

    with pytest.raises(ValueError, match="snapshot inquiry_id mismatch"):
        service.prepare_offer_version(other_id, _valid_snapshot())

    assert offers.save_calls == 0


def test_prepare_offer_version_active_order_blocks() -> None:
    offers = _CountingOfferRepository()
    _inquiries, orders, _offers, service = _world(
        inquiry=_sample_inquiry(), offers=offers
    )
    order = Order(
        order_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        source_inquiry_id=_INQUIRY_ID,
        created_at=_NOW,
        updated_at=_NOW,
    )
    version = OrderVersion(
        order_version_id="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        order_id=order.order_id,
        version_number=1,
        created_at=_NOW,
        event_date=date(2026, 8, 20),
        time_window_text="18:00–22:00",
        location_text="Hamburg",
        guest_count_estimate=80,
        planning_mode=PLANNING_MODES[0],
    )
    orders.save_order_with_initial_version(order, version)

    with pytest.raises(ValueError, match="active order blocks offer preparation"):
        service.prepare_offer_version(_INQUIRY_ID, _valid_snapshot())

    assert offers.save_calls == 0


def test_prepare_offer_version_existing_offer_blocks() -> None:
    offers = _CountingOfferRepository()
    offers.save(_existing_offer())
    _inquiries, _orders, _offers, service = _world(
        inquiry=_sample_inquiry(), offers=offers
    )

    with pytest.raises(ValueError, match="offer already exists for inquiry"):
        service.prepare_offer_version(_INQUIRY_ID, _valid_snapshot())

    assert offers.save_calls == 1


def test_prepare_offer_version_invalid_snapshot() -> None:
    offers = _CountingOfferRepository()
    _inquiries, _orders, _offers, service = _world(
        inquiry=_sample_inquiry(), offers=offers
    )
    payload = _valid_snapshot()
    payload["snapshot_hash"] = "sha256:" + ("f" * 64)

    with pytest.raises(ValueError, match="snapshot_hash mismatch"):
        service.prepare_offer_version(_INQUIRY_ID, payload)

    assert offers.save_calls == 0


def test_prepare_offer_version_repository_failure_leaves_no_offer() -> None:
    offers = _FailingOfferRepository(RuntimeError("disk full"))
    _inquiries, _orders, _offers, service = _world(
        inquiry=_sample_inquiry(), offers=offers
    )

    with pytest.raises(RuntimeError, match="disk full"):
        service.prepare_offer_version(_INQUIRY_ID, _valid_snapshot())

    assert offers.save_calls == 1
    assert offers.get_by_source_inquiry_id(_INQUIRY_ID) is None


def _service(
    offers: InMemoryOfferRepository,
) -> OfferService:
    inquiries = InMemoryInquiryRepository()
    orders = InMemoryOrderRepository()
    return OfferService(
        offers,
        inquiries,
        orders,
        now=lambda: _RECORDED_AT,
        today=lambda: date(2026, 7, 15),
    )


def _record_args() -> dict[str, object]:
    return {
        "sent_at": _SENT_AT,
        "channel": "email",
        "recipient_reference": "customer@example.invalid",
        "evidence_reference": "mail-123",
        "recorded_by": "office-panel",
    }


def test_record_sent_evidence_prepared_to_sent() -> None:
    offer = _existing_offer()
    version_id = offer.versions[0].offer_version_id
    offers = InMemoryOfferRepository()
    offers.save(offer)
    service = _service(offers)

    updated = service.record_sent_evidence(offer.offer_id, version_id, **_record_args())

    assert len(updated.sent_evidence) == 1
    evidence = updated.sent_evidence[0]
    assert evidence.sent_at == _SENT_AT
    assert evidence.recorded_at == _RECORDED_AT
    assert evidence.recorded_by == "office-panel"
    assert derive_offer_state(updated, version_id, today=date(2026, 7, 15)) == "Sent"


def test_record_sent_evidence_rejects_second_send() -> None:
    offer = _existing_offer()
    version_id = offer.versions[0].offer_version_id
    offers = InMemoryOfferRepository()
    offers.save(offer)
    service = _service(offers)
    service.record_sent_evidence(offer.offer_id, version_id, **_record_args())

    with pytest.raises(ValueError, match="sent evidence already exists"):
        service.record_sent_evidence(offer.offer_id, version_id, **_record_args())


def test_record_sent_evidence_rejects_withdrawn_version() -> None:
    offer = _existing_offer()
    version_id = offer.versions[0].offer_version_id
    withdrawn = Offer(
        offer_id=offer.offer_id,
        source_inquiry_id=offer.source_inquiry_id,
        created_at=offer.created_at,
        versions=offer.versions,
        withdrawal_evidence=(
            WithdrawalEvidence(
                offer_id=offer.offer_id,
                offer_version_id=version_id,
                withdrawn_at=_NOW,
                recorded_by="office",
            ),
        ),
    )
    offers = InMemoryOfferRepository()
    offers.save(withdrawn)
    service = _service(offers)

    with pytest.raises(ValueError, match="sent recording blocked"):
        service.record_sent_evidence(offer.offer_id, version_id, **_record_args())


def test_record_sent_evidence_rejects_when_acceptance_exists() -> None:
    offer = _existing_offer()
    version_id = offer.versions[0].offer_version_id
    accepted = Offer(
        offer_id=offer.offer_id,
        source_inquiry_id=offer.source_inquiry_id,
        created_at=offer.created_at,
        versions=offer.versions,
        sent_evidence=(
            SentEvidence(
                offer_id=offer.offer_id,
                offer_version_id=version_id,
                sent_at=_SENT_AT,
                recorded_at=_RECORDED_AT,
                channel="email",
                recipient_reference="customer@example.invalid",
                evidence_reference="mail-123",
                recorded_by="office-panel",
            ),
        ),
        acceptance_evidence=AcceptanceEvidence(
            acceptance_id="55555555-5555-4555-8555-555555555551",
            offer_id=offer.offer_id,
            accepted_offer_version_id=version_id,
            accepted_variant_id=_VARIANT_ID,
            accepted_at=_SENT_AT + timedelta(hours=1),
            recorded_at=_RECORDED_AT + timedelta(hours=1),
            channel="email",
            evidence_reference="reply-1",
            recorded_by="office-panel",
        ),
    )
    offers = InMemoryOfferRepository()
    offers.save(accepted)
    service = _service(offers)

    with pytest.raises(ValueError, match="acceptance blocks sent recording"):
        service.record_sent_evidence(offer.offer_id, version_id, **_record_args())


def test_record_sent_evidence_rejects_superseded_version() -> None:
    v1_id = _existing_offer().versions[0].offer_version_id
    v2_id = "44444444-4444-4444-8444-444444444442"
    v2 = OfferVersion(
        offer_version_id=v2_id,
        offer_id="11111111-1111-4111-8111-111111111111",
        version_number=2,
        created_at=_NOW + timedelta(hours=1),
        valid_until=date(2026, 7, 29),
        snapshot_id="99999999-9999-4999-8999-999999999992",
        snapshot_hash=_HASH,
        **_version_facts(),
        variants=(
            OfferVariant(
                variant_id="55555555-5555-4555-8555-555555555551",
                offer_version_id=v2_id,
                label="Variante v2",
                positions=_existing_offer().versions[0].variants[0].positions,
            ),
        ),
    )
    offer = Offer(
        offer_id="11111111-1111-4111-8111-111111111111",
        source_inquiry_id=_INQUIRY_ID,
        created_at=_NOW,
        versions=(_existing_offer().versions[0], v2),
        sent_evidence=(
            SentEvidence(
                offer_id="11111111-1111-4111-8111-111111111111",
                offer_version_id=v1_id,
                sent_at=_SENT_AT,
                recorded_at=_RECORDED_AT,
                channel="email",
                recipient_reference="customer@example.invalid",
                evidence_reference="mail-123",
                recorded_by="office-panel",
            ),
            SentEvidence(
                offer_id="11111111-1111-4111-8111-111111111111",
                offer_version_id=v2_id,
                sent_at=_SENT_AT + timedelta(hours=2),
                recorded_at=_RECORDED_AT + timedelta(hours=2),
                channel="email",
                recipient_reference="customer@example.invalid",
                evidence_reference="mail-456",
                recorded_by="office-panel",
            ),
        ),
    )
    offers = InMemoryOfferRepository()
    offers.save(offer)
    service = _service(offers)

    with pytest.raises(ValueError, match="sent evidence already exists"):
        service.record_sent_evidence(offer.offer_id, v1_id, **_record_args())


def test_prepare_offer_version_persists_event_and_payment_facts() -> None:
    offers = _CountingOfferRepository()
    _inquiries, _orders, _offers, service = _world(
        inquiry=_sample_inquiry(), offers=offers
    )
    payload = _valid_snapshot()

    offer = service.prepare_offer_version(_INQUIRY_ID, payload)
    version = offer.versions[0]

    assert version.event_date == date(2026, 8, 20)
    assert version.time_window_text == "18:00–22:00"
    assert version.location_text == "Hamburg"
    assert version.guest_count == 80
    assert version.planning_mode == "caterer_suggestion"
    assert version.payment_method == "RECHNUNG"
    assert version.payment_customer_visible_text == "Zahlung per Rechnung"


def test_prepare_offer_version_persists_null_guest_count() -> None:
    offers = InMemoryOfferRepository()
    _inquiries, _orders, _offers, service = _world(
        inquiry=_sample_inquiry(), offers=offers
    )
    payload = _valid_snapshot()
    event = dict(payload["event"])  # type: ignore[arg-type]
    event["guest_count"] = None
    payload["event"] = event
    payload["snapshot_hash"] = compute_snapshot_hash(payload)

    offer = service.prepare_offer_version(_INQUIRY_ID, payload)

    assert offer.versions[0].guest_count is None


def test_record_sent_evidence_append_failure_leaves_offer_unchanged() -> None:
    offer = _existing_offer()
    version_id = offer.versions[0].offer_version_id
    offers = _FailingAppendRepository(RuntimeError("append failed"))
    offers.save(offer)
    service = _service(offers)

    with pytest.raises(RuntimeError, match="append failed"):
        service.record_sent_evidence(offer.offer_id, version_id, **_record_args())

    assert offers.append_calls == 1
    assert offers.get(offer.offer_id) == offer


_ACCEPTED_AT = _SENT_AT + timedelta(seconds=1)


def _acceptance_args() -> dict[str, object]:
    return {
        "accepted_at": _ACCEPTED_AT,
        "channel": "email",
        "evidence_reference": "reply-1",
        "recorded_by": "office-panel",
        "note": None,
    }


def _sent_offer_state() -> tuple[Offer, str, InMemoryOfferRepository, OfferService]:
    offer = _existing_offer()
    version_id = offer.versions[0].offer_version_id
    offers = InMemoryOfferRepository()
    offers.save(offer)
    service = _service(offers)
    service.record_sent_evidence(offer.offer_id, version_id, **_record_args())
    return offer, version_id, offers, service


def test_record_acceptance_evidence_sent_to_accepted() -> None:
    offer, version_id, _offers, service = _sent_offer_state()

    updated = service.record_acceptance_evidence(
        offer.offer_id,
        version_id,
        _VARIANT_ID,
        **_acceptance_args(),
    )

    assert updated.acceptance_evidence is not None
    evidence = updated.acceptance_evidence
    assert evidence.accepted_variant_id == _VARIANT_ID
    assert evidence.accepted_at == _ACCEPTED_AT
    assert evidence.recorded_at == _RECORDED_AT
    assert evidence.recorded_by == "office-panel"
    assert (
        derive_offer_state(updated, version_id, today=date(2026, 7, 15)) == "Accepted"
    )


def test_record_acceptance_evidence_rejects_prepared() -> None:
    offer = _existing_offer()
    version_id = offer.versions[0].offer_version_id
    offers = InMemoryOfferRepository()
    offers.save(offer)
    service = _service(offers)

    with pytest.raises(ValueError, match="acceptance blocked"):
        service.record_acceptance_evidence(
            offer.offer_id, version_id, _VARIANT_ID, **_acceptance_args()
        )


def test_record_acceptance_evidence_rejects_expired() -> None:
    offer = _existing_offer()
    version_id = offer.versions[0].offer_version_id
    sent = Offer(
        offer_id=offer.offer_id,
        source_inquiry_id=offer.source_inquiry_id,
        created_at=offer.created_at,
        versions=offer.versions,
        sent_evidence=(
            SentEvidence(
                offer_id=offer.offer_id,
                offer_version_id=version_id,
                sent_at=_SENT_AT,
                recorded_at=_RECORDED_AT,
                channel="email",
                recipient_reference="customer@example.invalid",
                evidence_reference="mail-123",
                recorded_by="office-panel",
            ),
        ),
    )
    offers = InMemoryOfferRepository()
    offers.save(sent)
    service = OfferService(
        offers,
        InMemoryInquiryRepository(),
        InMemoryOrderRepository(),
        now=lambda: _RECORDED_AT,
        today=lambda: date(2026, 8, 1),
    )

    with pytest.raises(ValueError, match="acceptance blocked"):
        service.record_acceptance_evidence(
            offer.offer_id, version_id, _VARIANT_ID, **_acceptance_args()
        )


def test_record_acceptance_evidence_rejects_superseded() -> None:
    v1_id = _existing_offer().versions[0].offer_version_id
    v2_id = "44444444-4444-4444-8444-444444444442"
    v2 = OfferVersion(
        offer_version_id=v2_id,
        offer_id="11111111-1111-4111-8111-111111111111",
        version_number=2,
        created_at=_NOW + timedelta(hours=1),
        valid_until=date(2026, 7, 29),
        snapshot_id="99999999-9999-4999-8999-999999999992",
        snapshot_hash=_HASH,
        **_version_facts(),
        variants=(
            OfferVariant(
                variant_id="55555555-5555-4555-8555-555555555551",
                offer_version_id=v2_id,
                label="Variante v2",
                positions=_existing_offer().versions[0].variants[0].positions,
            ),
        ),
    )
    offer = Offer(
        offer_id="11111111-1111-4111-8111-111111111111",
        source_inquiry_id=_INQUIRY_ID,
        created_at=_NOW,
        versions=(_existing_offer().versions[0], v2),
        sent_evidence=(
            SentEvidence(
                offer_id="11111111-1111-4111-8111-111111111111",
                offer_version_id=v1_id,
                sent_at=_SENT_AT,
                recorded_at=_RECORDED_AT,
                channel="email",
                recipient_reference="customer@example.invalid",
                evidence_reference="mail-123",
                recorded_by="office-panel",
            ),
            SentEvidence(
                offer_id="11111111-1111-4111-8111-111111111111",
                offer_version_id=v2_id,
                sent_at=_SENT_AT + timedelta(hours=2),
                recorded_at=_RECORDED_AT + timedelta(hours=2),
                channel="email",
                recipient_reference="customer@example.invalid",
                evidence_reference="mail-456",
                recorded_by="office-panel",
            ),
        ),
    )
    offers = InMemoryOfferRepository()
    offers.save(offer)
    service = _service(offers)

    with pytest.raises(ValueError, match="acceptance blocked"):
        service.record_acceptance_evidence(
            offer.offer_id, v1_id, _VARIANT_ID, **_acceptance_args()
        )


def test_record_acceptance_evidence_rejects_withdrawn() -> None:
    offer = _existing_offer()
    version_id = offer.versions[0].offer_version_id
    withdrawn = Offer(
        offer_id=offer.offer_id,
        source_inquiry_id=offer.source_inquiry_id,
        created_at=offer.created_at,
        versions=offer.versions,
        sent_evidence=(
            SentEvidence(
                offer_id=offer.offer_id,
                offer_version_id=version_id,
                sent_at=_SENT_AT,
                recorded_at=_RECORDED_AT,
                channel="email",
                recipient_reference="customer@example.invalid",
                evidence_reference="mail-123",
                recorded_by="office-panel",
            ),
        ),
        withdrawal_evidence=(
            WithdrawalEvidence(
                offer_id=offer.offer_id,
                offer_version_id=version_id,
                withdrawn_at=_NOW + timedelta(hours=3),
                recorded_by="office",
            ),
        ),
    )
    offers = InMemoryOfferRepository()
    offers.save(withdrawn)
    service = _service(offers)

    with pytest.raises(ValueError, match="acceptance blocked"):
        service.record_acceptance_evidence(
            offer.offer_id, version_id, _VARIANT_ID, **_acceptance_args()
        )


def test_record_acceptance_evidence_rejects_wrong_variant() -> None:
    offer, version_id, _offers, service = _sent_offer_state()
    wrong_variant = "55555555-5555-4555-8555-555555555552"

    with pytest.raises(ValueError, match="accepted variant does not belong"):
        service.record_acceptance_evidence(
            offer.offer_id, version_id, wrong_variant, **_acceptance_args()
        )


def test_record_acceptance_evidence_rejects_second_acceptance() -> None:
    offer, version_id, _offers, service = _sent_offer_state()
    service.record_acceptance_evidence(
        offer.offer_id, version_id, _VARIANT_ID, **_acceptance_args()
    )

    with pytest.raises(ValueError, match="acceptance already exists"):
        service.record_acceptance_evidence(
            offer.offer_id, version_id, _VARIANT_ID, **_acceptance_args()
        )


def test_record_acceptance_evidence_blocks_later_send() -> None:
    offer, version_id, _offers, service = _sent_offer_state()
    service.record_acceptance_evidence(
        offer.offer_id, version_id, _VARIANT_ID, **_acceptance_args()
    )

    with pytest.raises(ValueError, match="acceptance blocks sent recording"):
        service.record_sent_evidence(offer.offer_id, version_id, **_record_args())


def test_record_acceptance_evidence_append_failure_leaves_offer_unchanged() -> None:
    offer = _existing_offer()
    version_id = offer.versions[0].offer_version_id
    sent = Offer(
        offer_id=offer.offer_id,
        source_inquiry_id=offer.source_inquiry_id,
        created_at=offer.created_at,
        versions=offer.versions,
        sent_evidence=(
            SentEvidence(
                offer_id=offer.offer_id,
                offer_version_id=version_id,
                sent_at=_SENT_AT,
                recorded_at=_RECORDED_AT,
                channel="email",
                recipient_reference="customer@example.invalid",
                evidence_reference="mail-123",
                recorded_by="office-panel",
            ),
        ),
    )
    offers = _FailingAppendRepository(RuntimeError("append failed"))
    offers.save(sent)
    service = _service(offers)

    with pytest.raises(RuntimeError, match="append failed"):
        service.record_acceptance_evidence(
            offer.offer_id, version_id, _VARIANT_ID, **_acceptance_args()
        )

    assert offers.append_calls == 1
    assert offers.get(offer.offer_id) == sent


def _accepted_offer_state() -> tuple[
    Offer,
    str,
    str,
    str,
    InMemoryOfferRepository,
    InMemoryOrderRepository,
    InMemoryInquiryRepository,
    OfferService,
]:
    inquiry = replace(
        _sample_inquiry(),
        location_text="Inquiry-only Berlin",
        guest_count_estimate=999,
    )
    inquiries, orders, offers, service = _world(inquiry=inquiry)
    offer = service.prepare_offer_version(_INQUIRY_ID, _valid_snapshot())
    version_id = offer.versions[0].offer_version_id
    service.record_sent_evidence(offer.offer_id, version_id, **_record_args())
    updated = service.record_acceptance_evidence(
        offer.offer_id,
        version_id,
        _VARIANT_ID,
        **_acceptance_args(),
    )
    assert updated.acceptance_evidence is not None
    return (
        updated,
        version_id,
        _VARIANT_ID,
        updated.acceptance_evidence.acceptance_id,
        offers,
        orders,
        inquiries,
        service,
    )


def test_convert_accepted_offer_happy_path() -> None:
    offer, version_id, variant_id, acceptance_id, offers, orders, _inq, service = (
        _accepted_offer_state()
    )

    updated, order, order_version = service.convert_accepted_offer(
        offer.offer_id,
        version_id,
        variant_id,
        acceptance_id,
    )

    assert updated.conversion_link is not None
    assert updated.conversion_link.order_id == order.order_id
    assert order_version.version_number == 1
    assert order_version.location_text == "Hamburg"
    assert order_version.guest_count_estimate == 80
    assert (
        derive_offer_state(updated, version_id, today=date(2026, 7, 15)) == "Converted"
    )
    assert len(orders.list_orders()) == 1


def test_convert_accepted_offer_order_version_from_offer_not_inquiry() -> None:
    (
        offer,
        version_id,
        variant_id,
        acceptance_id,
        _offers,
        _orders,
        inquiries,
        service,
    ) = _accepted_offer_state()
    inquiry = inquiries.get_by_id(_INQUIRY_ID)
    assert inquiry is not None
    assert inquiry.location_text == "Inquiry-only Berlin"
    assert inquiry.guest_count_estimate == 999

    _updated, _order, order_version = service.convert_accepted_offer(
        offer.offer_id,
        version_id,
        variant_id,
        acceptance_id,
    )

    assert order_version.location_text == "Hamburg"
    assert order_version.guest_count_estimate == 80


def test_convert_accepted_offer_idempotent_replay() -> None:
    offer, version_id, variant_id, acceptance_id, offers, orders, _inq, service = (
        _accepted_offer_state()
    )
    first = service.convert_accepted_offer(
        offer.offer_id, version_id, variant_id, acceptance_id
    )
    second = service.convert_accepted_offer(
        offer.offer_id, version_id, variant_id, acceptance_id
    )
    assert second[1].order_id == first[1].order_id
    assert len(orders.list_orders()) == 1
    assert offers.get(offer.offer_id) == second[0]


def test_convert_accepted_offer_storno_replay_same_order() -> None:
    offer, version_id, variant_id, acceptance_id, offers, orders, _inq, service = (
        _accepted_offer_state()
    )
    _updated, order, _ov = service.convert_accepted_offer(
        offer.offer_id, version_id, variant_id, acceptance_id
    )
    OperationalCoreService(orders).cancel_order(order.order_id)
    replay = service.convert_accepted_offer(
        offer.offer_id, version_id, variant_id, acceptance_id
    )
    assert replay[1].order_id == order.order_id
    assert len(orders.list_orders()) == 1
    assert offers.get(offer.offer_id) is not None
    assert offers.get(offer.offer_id).conversion_link is not None


def test_convert_accepted_offer_rejects_wrong_variant_or_acceptance() -> None:
    offer, version_id, variant_id, acceptance_id, _offers, orders, _inq, service = (
        _accepted_offer_state()
    )
    with pytest.raises(ValueError, match="accepted variant does not belong"):
        service.convert_accepted_offer(
            offer.offer_id,
            version_id,
            "55555555-5555-4555-8555-555555555551",
            acceptance_id,
        )
    with pytest.raises(ValueError, match="conversion blocked"):
        service.convert_accepted_offer(
            offer.offer_id,
            version_id,
            variant_id,
            "66666666-6666-4666-8666-666666666666",
        )
    assert len(orders.list_orders()) == 0


def test_convert_accepted_offer_rejects_active_order_without_link() -> None:
    (
        offer,
        version_id,
        variant_id,
        acceptance_id,
        _offers,
        orders,
        inquiries,
        service,
    ) = _accepted_offer_state()
    inquiry = inquiries.get_by_id(_INQUIRY_ID)
    assert inquiry is not None
    OrderService(orders).convert_inquiry_to_order(inquiry)
    with pytest.raises(ValueError, match="active order blocks conversion"):
        service.convert_accepted_offer(
            offer.offer_id, version_id, variant_id, acceptance_id
        )


def test_convert_accepted_offer_append_failure_leaves_no_order_or_link() -> None:
    (
        offer,
        version_id,
        variant_id,
        acceptance_id,
        offers,
        orders,
        inquiries,
        _service,
    ) = _accepted_offer_state()
    failing = _FailingConversionAppendRepository(RuntimeError("append failed"))
    stored = offers.get(offer.offer_id)
    assert stored is not None
    failing.save(stored)
    service = OfferService(
        failing,
        inquiries,
        orders,
        now=lambda: _RECORDED_AT,
        today=lambda: date(2026, 7, 15),
    )

    with pytest.raises(RuntimeError, match="append failed"):
        service.convert_accepted_offer(
            offer.offer_id, version_id, variant_id, acceptance_id
        )

    assert failing.append_calls == 1
    reloaded = failing.get(offer.offer_id)
    assert reloaded is not None
    assert reloaded.conversion_link is None
