"""Frozen customer-facing ANGEBOT / AUFTRAGSBESTÄTIGUNG snapshot.

OFFER_DOCUMENT_SNAPSHOT_V1: the initial customer document, frozen before the
first send and long before an Order exists. It anchors to one OfferVersion
and the single OfferVariant the office chose to present.

Boundary: this snapshot is never reused for a post-Order change. Changes to
an existing Order get their own document anchored to a candidate
OrderVersion (future ORDER_CHANGE_DOCUMENT_SNAPSHOT_V1), and this object is
also distinct from the post-Order OrderConfirmationDocumentSnapshot.

Schema 1 has no legacy tier: fulfillment and address facts are mandatory
from the start, so there is no NOT_STORED state to defend against.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from catering_system.domain.customer_document_projection import (
    CustomerAddress,
    customer_addresses_equal,
)
from catering_system.domain.order_payment_reminder import (
    PaymentMethod,
    validate_payment_method,
)

SCHEMA_VERSION = 1
SUPPORTED_SCHEMA_VERSIONS = frozenset({SCHEMA_VERSION})

OfferDocumentFulfillmentMode = Literal["DELIVERY", "PICKUP"]
OFFER_DOCUMENT_FULFILLMENT_MODES: tuple[OfferDocumentFulfillmentMode, ...] = (
    "DELIVERY",
    "PICKUP",
)

_DOCUMENT_HASH = re.compile(r"sha256:[0-9a-f]{64}\Z")

OfferDocumentBlockerCode = Literal[
    "OFFER_VERSION_NOT_PREPARED",
    "OFFER_VARIANT_NOT_FOUND",
    "MISSING_RECIPIENT_NAME",
    "MISSING_RECIPIENT_CONTACT",
    "INVOICE_ADDRESS_REQUIRED",
    "FULFILLMENT_MODE_REQUIRED",
    "DELIVERY_ADDRESS_REQUIRED_FOR_DELIVERY",
    "INVALID_COMMERCIAL_FACTS",
]

OFFER_DOCUMENT_BLOCKER_CODES: tuple[OfferDocumentBlockerCode, ...] = (
    "OFFER_VERSION_NOT_PREPARED",
    "OFFER_VARIANT_NOT_FOUND",
    "MISSING_RECIPIENT_NAME",
    "MISSING_RECIPIENT_CONTACT",
    "INVOICE_ADDRESS_REQUIRED",
    "FULFILLMENT_MODE_REQUIRED",
    "DELIVERY_ADDRESS_REQUIRED_FOR_DELIVERY",
    "INVALID_COMMERCIAL_FACTS",
)

_BLOCKER_SORT_ORDER: dict[OfferDocumentBlockerCode, int] = {
    code: index for index, code in enumerate(OFFER_DOCUMENT_BLOCKER_CODES)
}


def document_reference(offer_id: str, version_number: int) -> str:
    """Deterministic customer-visible reference — never a Rechnungsnummer.

    Derived from the Offer's own id, so it needs no sequential counter and
    no Order id (no Order exists yet at document time).
    """
    if not offer_id.strip():
        raise ValueError("offer_id is required")
    if version_number < 1:
        raise ValueError("version_number must be at least 1")
    return f"ANG-{offer_id[:8].upper()}-V{version_number}"


@dataclass(frozen=True)
class OfferDocumentBlocker:
    """One hard reason a customer offer document must not be created."""

    code: OfferDocumentBlockerCode
    detail: str | None = None

    def __post_init__(self) -> None:
        if self.code not in OFFER_DOCUMENT_BLOCKER_CODES:
            raise ValueError(f"unsupported offer document blocker code: {self.code!r}")
        if self.detail is not None and not self.detail.strip():
            raise ValueError("detail must not be blank when provided")


@dataclass(frozen=True)
class OfferDocumentEligibility:
    """Pure create decision for the customer offer document."""

    allowed: bool
    blockers: tuple[OfferDocumentBlocker, ...] = ()

    def __post_init__(self) -> None:
        if self.allowed != (self.blockers == ()):
            raise ValueError("allowed must equal (blockers == ())")


def sort_offer_document_blockers(
    blockers: tuple[OfferDocumentBlocker, ...],
) -> tuple[OfferDocumentBlocker, ...]:
    """Stable deterministic order for tests and API surfaces."""
    return tuple(
        sorted(
            blockers,
            key=lambda item: (_BLOCKER_SORT_ORDER[item.code], item.detail or ""),
        )
    )


class OfferDocumentCreationBlocked(Exception):
    """Controlled refusal to create the customer offer document."""

    def __init__(self, eligibility: OfferDocumentEligibility) -> None:
        if eligibility.allowed or not eligibility.blockers:
            raise ValueError(
                "OfferDocumentCreationBlocked requires a blocked eligibility"
            )
        self.eligibility = eligibility
        self.blockers = eligibility.blockers
        codes = ", ".join(blocker.code for blocker in eligibility.blockers)
        super().__init__(f"offer document creation blocked: {codes}")

    @property
    def primary_code(self) -> OfferDocumentBlockerCode:
        return self.blockers[0].code

    @property
    def codes(self) -> tuple[OfferDocumentBlockerCode, ...]:
        return tuple(blocker.code for blocker in self.blockers)


class OfferDocumentVariantConflictError(Exception):
    """One OfferVersion may present exactly one variant to the customer.

    A different variant is a different commercial offer and requires a new
    OfferVersion, never a second document for the same version.
    """

    def __init__(
        self,
        *,
        offer_version_id: str,
        existing_variant_id: str,
        requested_variant_id: str,
    ) -> None:
        self.offer_version_id = offer_version_id
        self.existing_variant_id = existing_variant_id
        self.requested_variant_id = requested_variant_id
        super().__init__(
            "offer document already exists for offer_version_id="
            f"{offer_version_id!r} with variant {existing_variant_id!r}; "
            f"requested {requested_variant_id!r}"
        )


class OfferDocumentHashMismatchError(Exception):
    """A persisted row failed re-verification and must not be trusted."""

    def __init__(
        self,
        *,
        offer_document_snapshot_id: str,
        recomputed: str,
        embedded: str,
        row: str,
    ) -> None:
        self.offer_document_snapshot_id = offer_document_snapshot_id
        self.recomputed = recomputed
        self.embedded = embedded
        self.row = row
        super().__init__(
            "offer document hash mismatch for "
            f"offer_document_snapshot_id={offer_document_snapshot_id!r}"
        )


@dataclass(frozen=True)
class OfferDocumentPosition:
    """One frozen customer-visible line. Cents are copied, never recomputed."""

    position_id: str
    kind: str
    name: str
    unit_net_cents: int
    net_total_cents: int
    vat_rate_percent: int
    vat_cents: int
    gross_cents: int
    related_position_id: str | None = None
    description: str | None = None
    composition: str | None = None
    quantity: str | None = None
    unit_label: str | None = None

    def __post_init__(self) -> None:
        if not self.position_id.strip():
            raise ValueError("position_id is required")
        if not self.name.strip():
            raise ValueError("name is required")
        for field, value in (
            ("unit_net_cents", self.unit_net_cents),
            ("net_total_cents", self.net_total_cents),
            ("vat_cents", self.vat_cents),
            ("gross_cents", self.gross_cents),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{field} must be an integer number of cents")
            if value < 0:
                raise ValueError(f"{field} must be non-negative")


@dataclass(frozen=True)
class OfferDocumentVatBucket:
    """Aggregated VAT band, summed once at freeze time from frozen cents."""

    rate_percent: int
    base_net_cents: int
    vat_cents: int

    def __post_init__(self) -> None:
        for field, value in (
            ("base_net_cents", self.base_net_cents),
            ("vat_cents", self.vat_cents),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{field} must be an integer number of cents")
            if value < 0:
                raise ValueError(f"{field} must be non-negative")


@dataclass(frozen=True)
class OfferDocumentSnapshot:
    """Immutable ANGEBOT / AUFTRAGSBESTÄTIGUNG content, frozen before sending."""

    offer_document_snapshot_id: str
    offer_id: str
    offer_version_id: str
    offer_variant_id: str
    document_reference: str
    created_at: datetime
    created_by: str
    recipient_name: str | None
    recipient_company: str | None
    recipient_email: str | None
    recipient_phone: str | None
    invoice_address: CustomerAddress
    fulfillment_mode: OfferDocumentFulfillmentMode
    delivery_address: CustomerAddress | None
    delivery_address_differs: bool
    event_date: date
    time_window_text: str
    location_text: str
    guest_count_estimate: int | None
    positions: tuple[OfferDocumentPosition, ...]
    vat_buckets: tuple[OfferDocumentVatBucket, ...]
    net_total_cents: int
    vat_total_cents: int
    gross_total_cents: int
    payment_method: PaymentMethod
    payment_customer_visible_text: str
    document_hash: str
    schema_version: int = SCHEMA_VERSION
    customer_title: str | None = None
    customer_introduction: str | None = None
    customer_notes: str | None = None
    document_warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.schema_version not in SUPPORTED_SCHEMA_VERSIONS:
            raise ValueError("unsupported offer document schema version")
        if not _DOCUMENT_HASH.fullmatch(self.document_hash):
            raise ValueError("document_hash must be sha256:<64 lowercase hex>")
        for field, value in (
            ("offer_document_snapshot_id", self.offer_document_snapshot_id),
            ("offer_id", self.offer_id),
            ("offer_version_id", self.offer_version_id),
            ("offer_variant_id", self.offer_variant_id),
            ("document_reference", self.document_reference),
            ("created_by", self.created_by),
        ):
            if not value.strip():
                raise ValueError(f"{field} is required")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")

        # Fulfillment is mandatory and binary here: UNKNOWN never reaches a
        # persisted customer document (eligibility refuses it first).
        if self.fulfillment_mode not in OFFER_DOCUMENT_FULFILLMENT_MODES:
            raise ValueError("fulfillment_mode must be DELIVERY or PICKUP")

        validate_payment_method(self.payment_method)
        if not self.payment_customer_visible_text.strip():
            raise ValueError("payment_customer_visible_text is required")

        # Rechnungsadresse is required for both modes; PICKUP only removes the
        # delivery-address requirement.
        if not _address_complete(self.invoice_address):
            raise ValueError(
                "invoice_address requires street, postal_code, city and country"
            )

        if self.fulfillment_mode == "PICKUP":
            if self.delivery_address is not None:
                raise ValueError("PICKUP must not store a delivery address")
            if self.delivery_address_differs:
                raise ValueError("PICKUP must not store delivery_address_differs=True")
        else:
            if self.delivery_address is None:
                raise ValueError("DELIVERY requires an effective delivery address")
            expected_differs = not customer_addresses_equal(
                self.invoice_address, self.delivery_address
            )
            if self.delivery_address_differs != expected_differs:
                raise ValueError("delivery_address_differs does not match addresses")

        money_fields: tuple[tuple[str, int], ...] = (
            ("net_total_cents", self.net_total_cents),
            ("vat_total_cents", self.vat_total_cents),
            ("gross_total_cents", self.gross_total_cents),
        )
        for money_field, money_value in money_fields:
            if isinstance(money_value, bool) or not isinstance(money_value, int):
                raise ValueError(f"{money_field} must be an integer number of cents")
            if money_value < 0:
                raise ValueError(f"{money_field} must be non-negative")


def _address_complete(address: CustomerAddress | None) -> bool:
    """True only when every structured invoice-address part is present."""
    if address is None:
        return False
    return all(
        (value or "").strip()
        for value in (
            address.street,
            address.postal_code,
            address.city,
            address.country,
        )
    )


def address_is_complete(address: CustomerAddress | None) -> bool:
    """Public form of the structural completeness rule (used by eligibility)."""
    return _address_complete(address)
