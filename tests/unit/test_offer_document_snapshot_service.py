"""OFFER_DOCUMENT_SNAPSHOT_V1 — prepare_offer_document service contract.

Eligibility, idempotency/variant-conflict, immutability against later
mutation, and the boundary rule that the persisted read path never touches
Inquiry/Offer/catalog.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from catering_system.domain.customer_document_projection import CustomerAddress
from catering_system.domain.inquiry_customer_snapshot import InquiryCustomerSnapshot
from catering_system.domain.offer_document_snapshot import (
    OfferDocumentCreationBlocked,
    OfferDocumentVariantConflictError,
)
from catering_system.repositories.in_memory_inquiry_repository import (
    InMemoryInquiryRepository,
)
from catering_system.repositories.in_memory_offer_document_snapshot_repository import (
    InMemoryOfferDocumentSnapshotRepository,
)
from catering_system.repositories.in_memory_offer_repository import (
    InMemoryOfferRepository,
)
from catering_system.repositories.in_memory_order_repository import (
    InMemoryOrderRepository,
)
from catering_system.services.offer_document_snapshot_service import (
    OfferDocumentNotFoundError,
    OfferDocumentSnapshotService,
)
from catering_system.services.offer_service import OfferService
from tests.unit.test_offer_service import _INQUIRY_ID, _sample_inquiry, _valid_snapshot

_NOW = datetime(2026, 7, 20, 9, 0, tzinfo=UTC)
_TODAY = date(2026, 7, 20)
_INVOICE = CustomerAddress(
    street="Bürostraße 1", postal_code="20095", city="Hamburg", country="DE"
)
_DELIVERY = CustomerAddress(
    street="Eventplatz 9", postal_code="20457", city="Hamburg", country="DE"
)


def _world(
    *,
    fulfillment_mode: str = "DELIVERY",
    invoice_address: CustomerAddress | None = _INVOICE,
    delivery_address: CustomerAddress | None = None,
    delivery_address_mode: str = "SAME_AS_INVOICE",
    contact_complete: bool = True,
):
    offers = InMemoryOfferRepository()
    inquiries = InMemoryInquiryRepository()
    orders = InMemoryOrderRepository()
    documents = InMemoryOfferDocumentSnapshotRepository()

    snapshot = InquiryCustomerSnapshot(
        company_name="ACME GmbH",
        contact_name="Anna" if contact_complete else None,
        email="anna@example.invalid" if contact_complete else None,
        phone="+49301234567" if contact_complete else None,
        invoice_address=invoice_address,
        delivery_address=delivery_address,
        delivery_address_mode=delivery_address_mode,
    )
    inquiry = replace(
        _sample_inquiry(),
        customer_snapshot=snapshot,
        fulfillment_mode=fulfillment_mode,
    )
    inquiries.save(inquiry)

    offer_service = OfferService(offers, inquiries, orders)
    offer = offer_service.prepare_offer_version(_INQUIRY_ID, _valid_snapshot())
    doc_service = OfferDocumentSnapshotService(
        offers, inquiries, documents, now=lambda: _NOW, today=lambda: _TODAY
    )
    return offers, inquiries, documents, doc_service, offer


# --- eligibility -----------------------------------------------------------------


def test_unknown_fulfillment_rejected() -> None:
    _offers, _inquiries, documents, doc_service, offer = _world(
        fulfillment_mode="UNKNOWN"
    )
    version = offer.versions[0]
    with pytest.raises(OfferDocumentCreationBlocked) as excinfo:
        doc_service.prepare_offer_document(
            offer.offer_id,
            version.offer_version_id,
            version.variants[0].variant_id,
            "office",
        )
    assert "FULFILLMENT_MODE_REQUIRED" in excinfo.value.codes
    assert documents.get_by_offer_version_id(version.offer_version_id) is None


def test_missing_invoice_address_rejected_for_delivery() -> None:
    _offers, _inquiries, documents, doc_service, offer = _world(
        fulfillment_mode="DELIVERY",
        invoice_address=None,
    )
    version = offer.versions[0]
    with pytest.raises(OfferDocumentCreationBlocked) as excinfo:
        doc_service.prepare_offer_document(
            offer.offer_id,
            version.offer_version_id,
            version.variants[0].variant_id,
            "office",
        )
    assert "INVOICE_ADDRESS_REQUIRED" in excinfo.value.codes
    assert documents.get_by_offer_version_id(version.offer_version_id) is None


def test_incomplete_invoice_address_rejected_for_pickup() -> None:
    incomplete = CustomerAddress(street="Only street")
    _offers, _inquiries, documents, doc_service, offer = _world(
        fulfillment_mode="PICKUP",
        invoice_address=incomplete,
        delivery_address_mode="UNKNOWN",
    )
    version = offer.versions[0]
    with pytest.raises(OfferDocumentCreationBlocked) as excinfo:
        doc_service.prepare_offer_document(
            offer.offer_id,
            version.offer_version_id,
            version.variants[0].variant_id,
            "office",
        )
    assert "INVOICE_ADDRESS_REQUIRED" in excinfo.value.codes
    # PICKUP never requires DELIVERY_ADDRESS_REQUIRED_FOR_DELIVERY.
    assert "DELIVERY_ADDRESS_REQUIRED_FOR_DELIVERY" not in excinfo.value.codes


def test_delivery_without_effective_address_rejected() -> None:
    _offers, _inquiries, documents, doc_service, offer = _world(
        fulfillment_mode="DELIVERY",
        invoice_address=_INVOICE,
        delivery_address_mode="UNKNOWN",
    )
    version = offer.versions[0]
    with pytest.raises(OfferDocumentCreationBlocked) as excinfo:
        doc_service.prepare_offer_document(
            offer.offer_id,
            version.offer_version_id,
            version.variants[0].variant_id,
            "office",
        )
    assert "DELIVERY_ADDRESS_REQUIRED_FOR_DELIVERY" in excinfo.value.codes


def test_pickup_with_invoice_address_and_no_delivery_address_succeeds() -> None:
    _offers, _inquiries, documents, doc_service, offer = _world(
        fulfillment_mode="PICKUP",
        invoice_address=_INVOICE,
        delivery_address_mode="UNKNOWN",
    )
    version = offer.versions[0]
    snap = doc_service.prepare_offer_document(
        offer.offer_id,
        version.offer_version_id,
        version.variants[0].variant_id,
        "office",
    )
    assert snap.fulfillment_mode == "PICKUP"
    assert snap.delivery_address is None
    assert snap.delivery_address_differs is False


def test_missing_recipient_name_rejected() -> None:
    """Reachable via the full flow: Offer preparation only requires
    email/phone completeness (inquiry_contact_complete), never name/company —
    so an Inquiry can have neither contact_name nor company_name and still
    reach document-snapshot eligibility."""
    _offers, _inquiries, documents, doc_service, offer = _world(
        fulfillment_mode="PICKUP",
        invoice_address=_INVOICE,
        delivery_address_mode="UNKNOWN",
    )
    version = offer.versions[0]
    inquiry = _inquiries.get_by_id(offer.source_inquiry_id)
    nameless = replace(inquiry.customer_snapshot, contact_name=None, company_name=None)
    _inquiries.update(replace(inquiry, customer_snapshot=nameless))
    with pytest.raises(OfferDocumentCreationBlocked) as excinfo:
        doc_service.prepare_offer_document(
            offer.offer_id,
            version.offer_version_id,
            version.variants[0].variant_id,
            "office",
        )
    assert "MISSING_RECIPIENT_NAME" in excinfo.value.codes


def test_missing_recipient_contact_rejected_at_eligibility_layer() -> None:
    """Offer preparation itself requires inquiry_contact_complete (email or
    phone), so this blocker cannot be reached through the full
    prepare_offer_document flow — it is tested directly against the pure
    eligibility function instead, the same way the sibling
    MISSING_CUSTOMER_CONTACT is tested for the Order-side document."""
    from datetime import date as _date

    from catering_system.domain.customer_document_projection import (
        CustomerDocumentRecipient,
    )
    from catering_system.services.offer_document_eligibility import (
        evaluate_offer_document_eligibility,
    )

    _offers, _inquiries, documents, doc_service, offer = _world()
    version = offer.versions[0]
    recipient = CustomerDocumentRecipient(
        name="Kunde",
        company_name=None,
        email=None,
        phone=None,
        invoice_address=_INVOICE,
        delivery_address=_INVOICE,
        delivery_address_differs=False,
    )
    result = evaluate_offer_document_eligibility(
        offer=offer,
        offer_version_id=version.offer_version_id,
        offer_variant_id=version.variants[0].variant_id,
        recipient=recipient,
        fulfillment_mode="DELIVERY",
        today=_date(2026, 7, 20),
    )
    codes = tuple(b.code for b in result.blockers)
    assert "MISSING_RECIPIENT_CONTACT" in codes


def test_unknown_variant_rejected() -> None:
    _offers, _inquiries, documents, doc_service, offer = _world()
    version = offer.versions[0]
    with pytest.raises(OfferDocumentCreationBlocked) as excinfo:
        doc_service.prepare_offer_document(
            offer.offer_id,
            version.offer_version_id,
            "not-a-real-variant",
            "office",
        )
    assert "OFFER_VARIANT_NOT_FOUND" in excinfo.value.codes


def test_unknown_offer_or_version_raises_not_found() -> None:
    _offers, _inquiries, documents, doc_service, offer = _world()
    version = offer.versions[0]
    with pytest.raises(OfferDocumentNotFoundError):
        doc_service.prepare_offer_document(
            "not-a-real-offer",
            version.offer_version_id,
            version.variants[0].variant_id,
            "office",
        )
    with pytest.raises(OfferDocumentNotFoundError):
        doc_service.prepare_offer_document(
            offer.offer_id,
            "not-a-real-version",
            version.variants[0].variant_id,
            "office",
        )


# --- idempotency / variant conflict ----------------------------------------------


def test_replay_same_version_and_variant_returns_same_snapshot() -> None:
    _offers, _inquiries, documents, doc_service, offer = _world()
    version = offer.versions[0]
    first = doc_service.prepare_offer_document(
        offer.offer_id,
        version.offer_version_id,
        version.variants[0].variant_id,
        "office",
    )
    second = doc_service.prepare_offer_document(
        offer.offer_id,
        version.offer_version_id,
        version.variants[0].variant_id,
        "office",
    )
    assert second.offer_document_snapshot_id == first.offer_document_snapshot_id
    assert second.document_hash == first.document_hash


def test_replay_works_after_offer_becomes_sent() -> None:
    offers, inquiries, documents, doc_service, offer = _world()
    version = offer.versions[0]
    first = doc_service.prepare_offer_document(
        offer.offer_id,
        version.offer_version_id,
        version.variants[0].variant_id,
        "office",
    )
    offer_service = OfferService(offers, inquiries, InMemoryOrderRepository())
    offer_service.record_sent_evidence(
        offer.offer_id,
        version.offer_version_id,
        sent_at=_NOW,
        channel="email",
        recipient_reference="anna@example.invalid",
        evidence_reference="msg-1",
        recorded_by="office",
    )
    replay = doc_service.prepare_offer_document(
        offer.offer_id,
        version.offer_version_id,
        version.variants[0].variant_id,
        "office",
    )
    assert replay.offer_document_snapshot_id == first.offer_document_snapshot_id


def test_different_variant_for_same_version_is_rejected() -> None:
    _offers, _inquiries, documents, doc_service, offer = _world()
    version = offer.versions[0]
    doc_service.prepare_offer_document(
        offer.offer_id,
        version.offer_version_id,
        version.variants[0].variant_id,
        "office",
    )
    with pytest.raises(OfferDocumentVariantConflictError):
        doc_service.prepare_offer_document(
            offer.offer_id,
            version.offer_version_id,
            "a-different-variant-id",
            "office",
        )


def test_replay_rejects_mismatched_offer_id() -> None:
    """REVIEW FIX: prepare_offer_document's replay branch must confirm the
    resolved snapshot belongs to the offer_id the caller supplied, not just
    the offer_version_id. A caller passing a different Offer's id together
    with a real version/variant from Offer A must be treated exactly like an
    unknown offer/version (404-equivalent), never a leak of Offer A's
    recipient/addresses/narrative/positions/totals."""
    offers, inquiries, documents, doc_service, offer_a = _world()
    version_a = offer_a.versions[0]
    variant_a_id = version_a.variants[0].variant_id
    snap = doc_service.prepare_offer_document(
        offer_a.offer_id, version_a.offer_version_id, variant_a_id, "office"
    )

    other_inquiry_id = "33333333-3333-4333-8333-333333333333"
    other_inquiry = replace(
        _sample_inquiry(inquiry_id=other_inquiry_id),
        customer_snapshot=InquiryCustomerSnapshot(
            company_name="Other GmbH",
            contact_name="Bea",
            email="bea@example.invalid",
            phone="+49309999999",
            invoice_address=_INVOICE,
            delivery_address=None,
            delivery_address_mode="SAME_AS_INVOICE",
        ),
        fulfillment_mode="DELIVERY",
    )
    inquiries.save(other_inquiry)
    offer_service = OfferService(offers, inquiries, InMemoryOrderRepository())
    offer_b = offer_service.prepare_offer_version(
        other_inquiry_id, _valid_snapshot(inquiry_id=other_inquiry_id)
    )
    assert offer_b.offer_id != offer_a.offer_id

    with pytest.raises(OfferDocumentNotFoundError):
        doc_service.prepare_offer_document(
            offer_b.offer_id, version_a.offer_version_id, variant_a_id, "office"
        )

    # Offer A's snapshot is untouched, and no second row was created for it.
    reloaded = documents.get_by_offer_version_id(version_a.offer_version_id)
    assert reloaded == snap
    assert len(documents._rows) == 1  # noqa: SLF001


def test_only_one_snapshot_row_exists_per_version(tmp_path: Path) -> None:
    _offers, _inquiries, documents, doc_service, offer = _world()
    version = offer.versions[0]
    for _ in range(3):
        doc_service.prepare_offer_document(
            offer.offer_id,
            version.offer_version_id,
            version.variants[0].variant_id,
            "office",
        )
    assert len(documents._rows) == 1  # noqa: SLF001


# --- immutability ------------------------------------------------------------------


def test_later_inquiry_mutation_does_not_alter_snapshot() -> None:
    offers, inquiries, documents, doc_service, offer = _world()
    version = offer.versions[0]
    snap = doc_service.prepare_offer_document(
        offer.offer_id,
        version.offer_version_id,
        version.variants[0].variant_id,
        "office",
    )
    inquiry = inquiries.get_by_id(offer.source_inquiry_id)
    inquiries.update(replace(inquiry, fulfillment_mode="PICKUP"))
    reloaded = documents.get_by_offer_version_id(version.offer_version_id)
    assert reloaded.fulfillment_mode == "DELIVERY"
    assert reloaded.document_hash == snap.document_hash


def test_new_offer_version_does_not_alter_old_snapshot() -> None:
    offers, inquiries, documents, doc_service, offer = _world()
    version = offer.versions[0]
    snap = doc_service.prepare_offer_document(
        offer.offer_id,
        version.offer_version_id,
        version.variants[0].variant_id,
        "office",
    )
    offer_service = OfferService(offers, inquiries, InMemoryOrderRepository())
    offer_service.record_sent_evidence(
        offer.offer_id,
        version.offer_version_id,
        sent_at=_NOW,
        channel="email",
        recipient_reference="anna@example.invalid",
        evidence_reference="msg-1",
        recorded_by="office",
    )
    next_snapshot = _valid_snapshot()
    next_snapshot["snapshot_id"] = "99999999-9999-4999-8999-999999999999"
    from catering_system.domain.offer_snapshot import compute_snapshot_hash

    next_snapshot["snapshot_hash"] = compute_snapshot_hash(next_snapshot)
    offer_service.prepare_next_offer_version(
        offer.offer_id,
        next_snapshot,
        expected_latest_version_number=1,
    )
    reloaded = documents.get_by_offer_version_id(version.offer_version_id)
    assert reloaded.offer_document_snapshot_id == snap.offer_document_snapshot_id
    assert reloaded.document_hash == snap.document_hash


# --- boundary ------------------------------------------------------------------


def test_persisted_read_path_does_not_import_inquiry_or_offer_repositories() -> None:
    root = Path(__file__).resolve().parents[2] / "src" / "catering_system"
    text = (root / "services" / "offer_document_snapshot_serialization.py").read_text(
        encoding="utf-8"
    )
    assert "InquiryRepository" not in text
    assert "OfferRepository" not in text
    assert "inquiry_repository" not in text.lower()
    assert "offer_repository" not in text.lower()


def test_hash_module_has_no_repository_or_catalog_dependency() -> None:
    root = Path(__file__).resolve().parents[2] / "src" / "catering_system"
    text = (root / "services" / "offer_document_snapshot_hash.py").read_text(
        encoding="utf-8"
    )
    assert "Repository" not in text
    assert "catalog" not in text.lower()
