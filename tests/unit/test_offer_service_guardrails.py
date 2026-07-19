"""OfferService guardrail and repository failure paths."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

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
from catering_system.services.order_service import OrderService
from tests.unit.test_offer_service import (
    _INQUIRY_ID,
    _acceptance_args,
    _accepted_offer_state,
    _record_args,
    _sample_inquiry,
    _valid_snapshot,
)


def _service() -> tuple[
    OfferService, InMemoryOfferRepository, InMemoryInquiryRepository
]:
    offers = InMemoryOfferRepository()
    inquiries = InMemoryInquiryRepository()
    orders = InMemoryOrderRepository()
    inquiries.save(_sample_inquiry())
    return OfferService(offers, inquiries, orders), offers, inquiries


def test_prepare_offer_rejects_snapshot_inquiry_mismatch() -> None:
    service, _, _ = _service()
    snapshot = _valid_snapshot()
    with pytest.raises(ValueError, match="snapshot inquiry_id mismatch"):
        service.prepare_offer_version("00000000-0000-4000-8000-000000000000", snapshot)


def test_prepare_offer_rejects_missing_inquiry() -> None:
    service, _, _ = _service()
    snapshot = _valid_snapshot()
    snapshot["inquiry_id"] = "00000000-0000-4000-8000-000000000000"
    from catering_system.domain.offer_snapshot import compute_snapshot_hash

    snapshot["snapshot_hash"] = compute_snapshot_hash(snapshot)
    with pytest.raises(KeyError):
        service.prepare_offer_version("00000000-0000-4000-8000-000000000000", snapshot)


def test_prepare_offer_rejects_when_active_order_exists() -> None:
    offers = InMemoryOfferRepository()
    inquiries = InMemoryInquiryRepository()
    orders = InMemoryOrderRepository()
    inquiry = _sample_inquiry()
    inquiries.save(inquiry)
    OrderService(orders).convert_inquiry_to_order(inquiry)
    service = OfferService(offers, inquiries, orders)
    with pytest.raises(ValueError, match="active order blocks offer preparation"):
        service.prepare_offer_version(_INQUIRY_ID, _valid_snapshot())


def test_record_sent_rejects_unknown_offer() -> None:
    service, _, _ = _service()
    with pytest.raises(KeyError):
        service.record_sent_evidence(
            "00000000-0000-4000-8000-000000000000",
            "00000000-0000-4000-8000-000000000001",
            sent_at=datetime.now(UTC),
            channel="email",
            recipient_reference="x@example.invalid",
            evidence_reference="mail-1",
            recorded_by="office",
        )


def test_record_sent_rejects_after_acceptance() -> None:
    service, offers, _ = _service()
    offer = service.prepare_offer_version(_INQUIRY_ID, _valid_snapshot())
    version_id = offer.versions[0].offer_version_id
    service.record_sent_evidence(offer.offer_id, version_id, **_record_args())
    service.record_acceptance_evidence(
        offer.offer_id,
        version_id,
        offer.versions[0].variants[0].variant_id,
        **_acceptance_args(),
    )
    with pytest.raises(ValueError, match="acceptance blocks sent recording"):
        service.record_sent_evidence(offer.offer_id, version_id, **_record_args())


def test_record_acceptance_rejects_unknown_variant() -> None:
    service, _, _ = _service()
    offer = service.prepare_offer_version(_INQUIRY_ID, _valid_snapshot())
    version_id = offer.versions[0].offer_version_id
    service.record_sent_evidence(offer.offer_id, version_id, **_record_args())
    with pytest.raises(ValueError, match="accepted variant does not belong"):
        service.record_acceptance_evidence(
            offer.offer_id,
            version_id,
            "00000000-0000-4000-8000-000000000099",
            **_acceptance_args(),
        )


def test_convert_rejects_when_not_allowed() -> None:
    service, _, _ = _service()
    offer = service.prepare_offer_version(_INQUIRY_ID, _valid_snapshot())
    version_id = offer.versions[0].offer_version_id
    variant_id = offer.versions[0].variants[0].variant_id
    with pytest.raises(ValueError, match="conversion blocked"):
        service.convert_accepted_offer(
            offer.offer_id,
            version_id,
            variant_id,
            "00000000-0000-4000-8000-000000000099",
        )


def test_convert_idempotent_when_link_already_exists() -> None:
    offer, version_id, variant_id, acceptance_id, _, _, inquiries, service = (
        _accepted_offer_state()
    )
    first_offer, first_order, first_version = service.convert_accepted_offer(
        offer.offer_id, version_id, variant_id, acceptance_id
    )
    second_offer, second_order, second_version = service.convert_accepted_offer(
        offer.offer_id, version_id, variant_id, acceptance_id
    )
    assert first_order.order_id == second_order.order_id
    assert first_version.order_version_id == second_version.order_version_id
    assert second_offer.conversion_link is not None
    assert inquiries.get_by_id(_INQUIRY_ID) is not None
