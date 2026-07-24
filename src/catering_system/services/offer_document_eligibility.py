"""Pure create eligibility for the customer offer document.

No repositories, no persistence, no rendering: value objects in, decision
out. Mirrors services/customer_document_eligibility.py, but the fulfillment
and address rules are the OFFER_DOCUMENT_SNAPSHOT_V1 ones.
"""

from __future__ import annotations

from datetime import date

from catering_system.domain.customer_document_projection import (
    CustomerDocumentRecipient,
)
from catering_system.domain.inquiry import FulfillmentMode
from catering_system.domain.offer import Offer, derive_offer_state
from catering_system.domain.offer_document_snapshot import (
    OfferDocumentBlocker,
    OfferDocumentEligibility,
    address_is_complete,
    sort_offer_document_blockers,
)

_PLACEHOLDER_NAME = "Kunde"


def evaluate_offer_document_eligibility(
    *,
    offer: Offer,
    offer_version_id: str,
    offer_variant_id: str,
    recipient: CustomerDocumentRecipient,
    fulfillment_mode: FulfillmentMode,
    today: date,
) -> OfferDocumentEligibility:
    """Decide whether a NEW offer document may be frozen for this version."""
    blockers: list[OfferDocumentBlocker] = []

    version = next(
        (item for item in offer.versions if item.offer_version_id == offer_version_id),
        None,
    )
    if version is None:
        # An unknown version cannot carry a variant either; report both facts
        # rather than guessing which one the caller got wrong.
        blockers.append(OfferDocumentBlocker(code="OFFER_VERSION_NOT_PREPARED"))
        blockers.append(OfferDocumentBlocker(code="OFFER_VARIANT_NOT_FOUND"))
    else:
        if derive_offer_state(offer, offer_version_id, today=today) != "Prepared":
            blockers.append(OfferDocumentBlocker(code="OFFER_VERSION_NOT_PREPARED"))
        if not any(
            variant.variant_id == offer_variant_id for variant in version.variants
        ):
            blockers.append(OfferDocumentBlocker(code="OFFER_VARIANT_NOT_FOUND"))

    if not _has_usable_name(recipient):
        blockers.append(OfferDocumentBlocker(code="MISSING_RECIPIENT_NAME"))

    if not _has_usable_contact(recipient):
        blockers.append(OfferDocumentBlocker(code="MISSING_RECIPIENT_CONTACT"))

    # Rechnungsadresse is required for BOTH modes. PICKUP removes only the
    # delivery-address requirement, never the invoice-address requirement.
    if not address_is_complete(recipient.invoice_address):
        blockers.append(OfferDocumentBlocker(code="INVOICE_ADDRESS_REQUIRED"))

    # fulfillment_mode is the sole source for these two blockers — never
    # inferred from address presence, text or payment.
    if fulfillment_mode == "UNKNOWN":
        blockers.append(OfferDocumentBlocker(code="FULFILLMENT_MODE_REQUIRED"))
    elif fulfillment_mode == "DELIVERY" and recipient.delivery_address is None:
        blockers.append(
            OfferDocumentBlocker(code="DELIVERY_ADDRESS_REQUIRED_FOR_DELIVERY")
        )

    if version is not None and not _commercial_facts_valid(version, offer_variant_id):
        blockers.append(OfferDocumentBlocker(code="INVALID_COMMERCIAL_FACTS"))

    ordered = sort_offer_document_blockers(tuple(blockers))
    return OfferDocumentEligibility(allowed=not ordered, blockers=ordered)


def _has_usable_name(recipient: CustomerDocumentRecipient) -> bool:
    name = recipient.name.strip()
    if name and name != _PLACEHOLDER_NAME:
        return True
    return bool((recipient.company_name or "").strip())


def _has_usable_contact(recipient: CustomerDocumentRecipient) -> bool:
    email = (recipient.email or "").strip()
    phone = (recipient.phone or "").strip()
    return bool(email) or bool(phone)


def _commercial_facts_valid(version: object, offer_variant_id: str) -> bool:
    """Defense in depth: OfferVersion invariants should already guarantee this.

    Only checks that the selected variant carries at least one position and
    that payment terms are present; per-position cents are validated by the
    OfferPosition dataclass itself at construction time.
    """
    variant = next(
        (
            item
            for item in getattr(version, "variants", ())
            if item.variant_id == offer_variant_id
        ),
        None,
    )
    if variant is None:
        return True  # OFFER_VARIANT_NOT_FOUND already reports this case
    if not variant.positions:
        return False
    return bool(getattr(version, "payment_customer_visible_text", "").strip())
