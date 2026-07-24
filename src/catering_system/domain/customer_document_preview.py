"""Live customer-document preview — CUSTOMER_DOCUMENT_PROJECTION_V1-D.

Read model for operators before create. Not a persisted document identity.
"""

from __future__ import annotations

from dataclasses import dataclass

from catering_system.domain.customer_document_eligibility import DocumentBlocker
from catering_system.domain.customer_document_projection import (
    CustomerDocumentCommercialReference,
    CustomerDocumentEvent,
    CustomerDocumentPosition,
    CustomerDocumentRecipient,
    CustomerDocumentWarning,
    DocumentType,
    DOCUMENT_TYPES,
)
from catering_system.domain.inquiry import FulfillmentMode, validate_fulfillment_mode
from catering_system.domain.order_payment_reminder import (
    PaymentMethod,
    validate_payment_method,
)


@dataclass(frozen=True)
class CustomerDocumentPreview:
    """Facts + warnings + eligibility for a document that does not yet exist."""

    document_type: DocumentType
    eligible: bool
    warnings: tuple[CustomerDocumentWarning, ...]
    blockers: tuple[DocumentBlocker, ...]
    recipient: CustomerDocumentRecipient
    event: CustomerDocumentEvent | None = None
    commercial_reference: CustomerDocumentCommercialReference | None = None
    positions: tuple[CustomerDocumentPosition, ...] = ()
    payment_method: PaymentMethod | None = None
    payment_customer_visible_text: str | None = None
    net_total_cents: int | None = None
    vat_total_cents: int | None = None
    gross_total_cents: int | None = None
    fulfillment_mode: FulfillmentMode = "UNKNOWN"

    def __post_init__(self) -> None:
        if self.document_type not in DOCUMENT_TYPES:
            raise ValueError("unsupported document_type")
        if self.eligible != (self.blockers == ()):
            raise ValueError("eligible must equal (blockers == ())")
        if self.payment_method is not None:
            validate_payment_method(self.payment_method)
        validate_fulfillment_mode(self.fulfillment_mode)
        money = (
            self.net_total_cents,
            self.vat_total_cents,
            self.gross_total_cents,
        )
        if any(value is None for value in money) and any(
            value is not None for value in money
        ):
            raise ValueError("money totals must be all set or all unset")
        if self.commercial_reference is None and self.positions:
            raise ValueError("positions require commercial_reference")
