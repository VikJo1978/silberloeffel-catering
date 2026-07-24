"""Freeze and read the customer ANGEBOT / AUFTRAGSBESTÄTIGUNG document.

Lifecycle: idempotency lookup → load Offer/Version/Variant → read Inquiry
once for structured customer facts → evaluate eligibility → build frozen
facts from already-frozen cents → hash → insert once.

After insertion there is no live fallback: reads go through the snapshot
repository only, and the future PDF renderer will receive the snapshot
alone. No Offer/Inquiry/catalog access happens on the read path.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime

from catering_system.domain.customer_document_projection import (
    WARNING_DELIVERY_ADDRESS_DIFFERS,
    CustomerDocumentRecipient,
)
from catering_system.domain.offer import Offer, OfferVariant, OfferVersion
from catering_system.domain.offer_document_snapshot import (
    OfferDocumentCreationBlocked,
    OfferDocumentFulfillmentMode,
    OfferDocumentPosition,
    OfferDocumentSnapshot,
    OfferDocumentVariantConflictError,
    OfferDocumentVatBucket,
    document_reference,
)
from catering_system.repositories.inquiry_repository import InquiryRepository
from catering_system.repositories.offer_document_snapshot_repository import (
    OfferDocumentSnapshotRepository,
)
from catering_system.repositories.offer_repository import OfferRepository
from catering_system.services.customer_document_projection import (
    build_customer_document_recipient,
)
from catering_system.services.offer_document_eligibility import (
    evaluate_offer_document_eligibility,
)
from catering_system.services.offer_document_snapshot_hash import compute_document_hash


class OfferDocumentNotFoundError(LookupError):
    """Raised when the requested Offer, OfferVersion or variant is unknown."""


class OfferDocumentSnapshotService:
    def __init__(
        self,
        offer_repository: OfferRepository,
        inquiry_repository: InquiryRepository,
        snapshot_repository: OfferDocumentSnapshotRepository,
        *,
        now: Callable[[], datetime] | None = None,
        today: Callable[[], date] | None = None,
    ) -> None:
        self._offers = offer_repository
        self._inquiries = inquiry_repository
        self._snapshots = snapshot_repository
        self._now = now or (lambda: datetime.now(UTC))
        self._today = today or date.today

    def prepare_offer_document(
        self,
        offer_id: str,
        offer_version_id: str,
        offer_variant_id: str,
        created_by: str,
    ) -> OfferDocumentSnapshot:
        # 1/2. Idempotency first, before any state gate: a replay must keep
        # working after the Offer has moved on to Sent.
        existing = self._snapshots.get_by_offer_version_id(offer_version_id)
        if existing is not None:
            if existing.offer_variant_id != offer_variant_id:
                raise OfferDocumentVariantConflictError(
                    offer_version_id=offer_version_id,
                    existing_variant_id=existing.offer_variant_id,
                    requested_variant_id=offer_variant_id,
                )
            return existing

        # 3/4. Load exact Offer, OfferVersion and OfferVariant.
        offer = self._offers.get(offer_id)
        if offer is None:
            raise OfferDocumentNotFoundError(offer_id)
        version = next(
            (
                item
                for item in offer.versions
                if item.offer_version_id == offer_version_id
            ),
            None,
        )
        if version is None:
            raise OfferDocumentNotFoundError(offer_version_id)

        # 6. Read the Inquiry exactly once for the structured customer facts
        # the OfferVersion does not carry.
        inquiry = self._inquiries.get_by_id(offer.source_inquiry_id)
        fulfillment_mode = (
            inquiry.fulfillment_mode if inquiry is not None else "UNKNOWN"
        )
        # 7. Reuse the existing recipient/address resolution (it already
        # suppresses delivery address and the differs warning for PICKUP).
        recipient = build_customer_document_recipient(
            inquiry, fulfillment_mode=fulfillment_mode
        )

        # 5/8. Every blocker is evaluated before anything is written.
        eligibility = evaluate_offer_document_eligibility(
            offer=offer,
            offer_version_id=offer_version_id,
            offer_variant_id=offer_variant_id,
            recipient=recipient,
            fulfillment_mode=fulfillment_mode,
            today=self._today(),
        )
        if not eligibility.allowed:
            raise OfferDocumentCreationBlocked(eligibility)

        variant = next(
            item for item in version.variants if item.variant_id == offer_variant_id
        )

        # 9-12. Build frozen facts, derive the reference, hash, insert once.
        snapshot = _build_snapshot(
            offer=offer,
            version=version,
            variant=variant,
            recipient=recipient,
            fulfillment_mode=fulfillment_mode,
            created_at=self._now(),
            created_by=created_by,
        )
        self._snapshots.insert(snapshot)
        return snapshot

    def get_by_id(
        self, offer_document_snapshot_id: str
    ) -> OfferDocumentSnapshot | None:
        return self._snapshots.get_by_id(offer_document_snapshot_id)

    def get_by_offer_version_id(
        self, offer_version_id: str
    ) -> OfferDocumentSnapshot | None:
        return self._snapshots.get_by_offer_version_id(offer_version_id)


def _build_snapshot(
    *,
    offer: Offer,
    version: OfferVersion,
    variant: OfferVariant,
    recipient: CustomerDocumentRecipient,
    fulfillment_mode: str,
    created_at: datetime,
    created_by: str,
) -> OfferDocumentSnapshot:
    """Pure assembly from already-frozen values. No price or VAT is recomputed."""
    positions = tuple(_position(item) for item in variant.positions)
    vat_buckets = _vat_buckets(variant)
    net_total = sum(item.net_total_cents for item in variant.positions)
    vat_total = sum(item.vat_amount_cents for item in variant.positions)
    gross_total = sum(item.gross_total_cents for item in variant.positions)

    mode: OfferDocumentFulfillmentMode = (
        "PICKUP" if fulfillment_mode == "PICKUP" else "DELIVERY"
    )
    warnings = tuple(
        warning
        for warning in recipient.warnings
        if warning == WARNING_DELIVERY_ADDRESS_DIFFERS
    )
    assert recipient.invoice_address is not None  # guaranteed by eligibility
    snapshot = OfferDocumentSnapshot(
        offer_document_snapshot_id=str(uuid.uuid4()),
        offer_id=offer.offer_id,
        offer_version_id=version.offer_version_id,
        offer_variant_id=variant.variant_id,
        document_reference=document_reference(offer.offer_id, version.version_number),
        created_at=created_at,
        created_by=created_by,
        recipient_name=recipient.name,
        recipient_company=recipient.company_name,
        recipient_email=recipient.email,
        recipient_phone=recipient.phone,
        invoice_address=recipient.invoice_address,
        fulfillment_mode=mode,
        delivery_address=recipient.delivery_address,
        delivery_address_differs=recipient.delivery_address_differs,
        event_date=version.event_date,
        time_window_text=version.time_window_text,
        location_text=version.location_text,
        guest_count_estimate=version.guest_count,
        customer_title=version.customer_title,
        customer_introduction=version.customer_introduction,
        customer_notes=version.customer_notes,
        positions=positions,
        vat_buckets=vat_buckets,
        net_total_cents=net_total,
        vat_total_cents=vat_total,
        gross_total_cents=gross_total,
        payment_method=version.payment_method,
        payment_customer_visible_text=version.payment_customer_visible_text,
        document_hash="sha256:" + "0" * 64,
        document_warnings=warnings,
    )
    return _with_hash(snapshot)


def _with_hash(snapshot: OfferDocumentSnapshot) -> OfferDocumentSnapshot:
    """Second construction with the real hash (the field is part of identity)."""
    from dataclasses import replace

    return replace(snapshot, document_hash=compute_document_hash(snapshot))


def _position(position: object) -> OfferDocumentPosition:
    return OfferDocumentPosition(
        position_id=position.position_id,  # type: ignore[attr-defined]
        kind=position.kind,  # type: ignore[attr-defined]
        name=position.name,  # type: ignore[attr-defined]
        unit_net_cents=position.unit_net_cents,  # type: ignore[attr-defined]
        net_total_cents=position.net_total_cents,  # type: ignore[attr-defined]
        vat_rate_percent=position.vat_rate_percent,  # type: ignore[attr-defined]
        vat_cents=position.vat_amount_cents,  # type: ignore[attr-defined]
        gross_cents=position.gross_total_cents,  # type: ignore[attr-defined]
        related_position_id=position.related_position_id,  # type: ignore[attr-defined]
        description=position.description,  # type: ignore[attr-defined]
        composition=position.composition,  # type: ignore[attr-defined]
        quantity=(
            format(position.quantity, "f")  # type: ignore[attr-defined]
            if position.quantity is not None  # type: ignore[attr-defined]
            else None
        ),
        unit_label=position.unit_label,  # type: ignore[attr-defined]
    )


def _vat_buckets(variant: OfferVariant) -> tuple[OfferDocumentVatBucket, ...]:
    """Aggregate frozen per-position cents into stable, rate-ordered bands."""
    bases: dict[int, int] = {}
    amounts: dict[int, int] = {}
    for position in variant.positions:
        bases[position.vat_rate_percent] = (
            bases.get(position.vat_rate_percent, 0) + position.net_total_cents
        )
        amounts[position.vat_rate_percent] = (
            amounts.get(position.vat_rate_percent, 0) + position.vat_amount_cents
        )
    return tuple(
        OfferDocumentVatBucket(
            rate_percent=rate,
            base_net_cents=bases[rate],
            vat_cents=amounts[rate],
        )
        for rate in sorted(bases)
    )
