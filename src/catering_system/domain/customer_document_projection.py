"""Customer-facing document fact projection — CUSTOMER_DOCUMENT_PROJECTION_V1 PR-A.

Frozen read-model separating document facts from persistence, eligibility,
and rendering. Commercial money/menu come from OrderCommercialSnapshot;
customer/address facts come from Inquiry customer data — never from Offer
or intake_message re-parse in builders.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from catering_system.domain.inquiry import PlanningMode
from catering_system.domain.order_payment_reminder import (
    PaymentMethod,
    validate_payment_method,
)

DocumentType = Literal["ORDER_CONFIRMATION"]
DOCUMENT_TYPES: tuple[DocumentType, ...] = ("ORDER_CONFIRMATION",)

CustomerDocumentWarning = Literal["DELIVERY_ADDRESS_DIFFERS_FROM_INVOICE"]
WARNING_DELIVERY_ADDRESS_DIFFERS: CustomerDocumentWarning = (
    "DELIVERY_ADDRESS_DIFFERS_FROM_INVOICE"
)

_MAX_TEXT = 20_000
_MAX_LABEL = 500


def _require_text(value: str, field: str) -> None:
    if not value.strip():
        raise ValueError(f"{field} is required")


def _require_aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")


def _require_non_negative_cents(value: int, field: str) -> None:
    if value < 0:
        raise ValueError(f"{field} must be non-negative")


def _optional_bounded_text(value: str | None, field: str, *, max_len: int) -> None:
    if value is None:
        return
    _require_text(value, field)
    if len(value) > max_len:
        raise ValueError(f"{field} exceeds length limit")


@dataclass(frozen=True)
class CustomerAddress:
    """Postal address fact for invoice or delivery on a customer document."""

    street: str | None = None
    postal_code: str | None = None
    city: str | None = None
    country: str | None = None

    def __post_init__(self) -> None:
        for field, value in (
            ("street", self.street),
            ("postal_code", self.postal_code),
            ("city", self.city),
            ("country", self.country),
        ):
            _optional_bounded_text(value, field, max_len=_MAX_LABEL)


@dataclass(frozen=True)
class CustomerDocumentRecipient:
    """Customer/contact block for a document — includes dual address slots."""

    name: str
    email: str | None = None
    company_name: str | None = None
    phone: str | None = None
    invoice_address: CustomerAddress | None = None
    delivery_address: CustomerAddress | None = None
    delivery_address_differs: bool = False
    warnings: tuple[CustomerDocumentWarning, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.name, "name")
        _optional_bounded_text(self.email, "email", max_len=_MAX_LABEL)
        _optional_bounded_text(self.company_name, "company_name", max_len=_MAX_LABEL)
        _optional_bounded_text(self.phone, "phone", max_len=_MAX_LABEL)
        expected_differs = (
            self.invoice_address is not None
            and self.delivery_address is not None
            and self.invoice_address != self.delivery_address
        )
        if self.delivery_address_differs != expected_differs:
            raise ValueError("delivery_address_differs does not match addresses")
        if expected_differs:
            if WARNING_DELIVERY_ADDRESS_DIFFERS not in self.warnings:
                raise ValueError(
                    "delivery address differs requires "
                    f"{WARNING_DELIVERY_ADDRESS_DIFFERS}"
                )
        elif WARNING_DELIVERY_ADDRESS_DIFFERS in self.warnings:
            raise ValueError(
                f"{WARNING_DELIVERY_ADDRESS_DIFFERS} requires differing addresses"
            )


@dataclass(frozen=True)
class CustomerDocumentCommercialReference:
    """Provenance of the commercial state used for the document."""

    snapshot_id: str
    source_offer_id: str
    source_offer_version_id: str
    variant_label: str

    def __post_init__(self) -> None:
        _require_text(self.snapshot_id, "snapshot_id")
        _require_text(self.source_offer_id, "source_offer_id")
        _require_text(self.source_offer_version_id, "source_offer_version_id")
        _require_text(self.variant_label, "variant_label")


@dataclass(frozen=True)
class CustomerDocumentEvent:
    """Event facts from OrderVersion for the customer document."""

    order_id: str
    order_version_id: str
    version_number: int
    event_date: date
    time_window_text: str
    location_text: str
    guest_count_estimate: int | None
    planning_mode: PlanningMode

    def __post_init__(self) -> None:
        _require_text(self.order_id, "order_id")
        _require_text(self.order_version_id, "order_version_id")
        if self.version_number < 1:
            raise ValueError("version_number must be >= 1")
        _require_text(self.time_window_text, "time_window_text")
        _require_text(self.location_text, "location_text")
        if self.guest_count_estimate is not None and self.guest_count_estimate < 0:
            raise ValueError("guest_count_estimate must be non-negative")


@dataclass(frozen=True)
class CustomerDocumentPosition:
    """Customer-visible commercial line derived from OrderCommercialPosition."""

    position_id: str
    kind: str
    name: str
    unit_net_cents: int
    net_total_cents: int
    vat_rate_percent: int
    vat_amount_cents: int
    gross_total_cents: int
    related_position_id: str | None = None
    description: str | None = None
    composition: str | None = None
    quantity: str | None = None
    unit_label: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.position_id, "position_id")
        _require_text(self.kind, "kind")
        _require_text(self.name, "name")
        if self.vat_rate_percent not in (7, 19):
            raise ValueError("vat_rate_percent must be 7 or 19")
        for field, value in (
            ("unit_net_cents", self.unit_net_cents),
            ("net_total_cents", self.net_total_cents),
            ("vat_amount_cents", self.vat_amount_cents),
            ("gross_total_cents", self.gross_total_cents),
        ):
            _require_non_negative_cents(value, field)
        _optional_bounded_text(
            self.related_position_id, "related_position_id", max_len=_MAX_LABEL
        )
        _optional_bounded_text(self.description, "description", max_len=_MAX_TEXT)
        _optional_bounded_text(self.composition, "composition", max_len=_MAX_TEXT)
        _optional_bounded_text(self.quantity, "quantity", max_len=_MAX_LABEL)
        _optional_bounded_text(self.unit_label, "unit_label", max_len=_MAX_LABEL)


@dataclass(frozen=True)
class CustomerDocumentProjection:
    """Immutable customer-document fact bundle for later render/delivery."""

    document_type: DocumentType
    document_id: str
    created_at: datetime
    recipient: CustomerDocumentRecipient
    commercial_reference: CustomerDocumentCommercialReference
    event: CustomerDocumentEvent
    positions: tuple[CustomerDocumentPosition, ...]
    payment_method: PaymentMethod
    payment_customer_visible_text: str
    net_total_cents: int
    vat_total_cents: int
    gross_total_cents: int

    def __post_init__(self) -> None:
        if self.document_type not in DOCUMENT_TYPES:
            raise ValueError("unsupported document_type")
        _require_text(self.document_id, "document_id")
        _require_aware(self.created_at, "created_at")
        if not self.positions:
            raise ValueError("positions must not be empty")
        validate_payment_method(self.payment_method)
        _require_text(
            self.payment_customer_visible_text, "payment_customer_visible_text"
        )
        if len(self.payment_customer_visible_text) > _MAX_TEXT:
            raise ValueError("payment_customer_visible_text exceeds length limit")
        for field, value in (
            ("net_total_cents", self.net_total_cents),
            ("vat_total_cents", self.vat_total_cents),
            ("gross_total_cents", self.gross_total_cents),
        ):
            _require_non_negative_cents(value, field)
        expected_net = sum(p.net_total_cents for p in self.positions)
        expected_vat = sum(p.vat_amount_cents for p in self.positions)
        expected_gross = sum(p.gross_total_cents for p in self.positions)
        if (
            self.net_total_cents != expected_net
            or self.vat_total_cents != expected_vat
            or self.gross_total_cents != expected_gross
        ):
            raise ValueError("totals must equal sum of position money fields")
