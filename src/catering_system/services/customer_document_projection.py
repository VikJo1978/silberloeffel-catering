"""Pure builders for CustomerDocumentProjection — FOUNDATION_V1.

No repositories. No Offer. No intake_message parsing. No HTML.
"""

from __future__ import annotations

from datetime import datetime

from catering_system.domain.customer_document_projection import (
    WARNING_DELIVERY_ADDRESS_DIFFERS,
    CustomerAddress,
    CustomerDocumentCommercialReference,
    CustomerDocumentEvent,
    CustomerDocumentPosition,
    CustomerDocumentProjection,
    CustomerDocumentRecipient,
    CustomerDocumentWarning,
    DocumentType,
    customer_addresses_equal,
)
from catering_system.domain.inquiry import FulfillmentMode, Inquiry
from catering_system.domain.inquiry_customer_snapshot import InquiryCustomerSnapshot
from catering_system.domain.order import OrderVersion
from catering_system.domain.order_commercial_snapshot import (
    OrderCommercialPosition,
    OrderCommercialSnapshot,
)
from catering_system.services.order_print_projection_service import (
    format_quantity_display,
)


def build_customer_document_recipient(
    inquiry: Inquiry | None,
    *,
    invoice_address: CustomerAddress | None = None,
    delivery_address: CustomerAddress | None = None,
    fulfillment_mode: FulfillmentMode = "UNKNOWN",
) -> CustomerDocumentRecipient:
    """Map Inquiry.customer_snapshot to recipient (CUSTOMER_ADDRESS_SOURCE_V1-A).

    Optional address kwargs override snapshot addresses for tests only. When
    kwargs are omitted, delivery_address_mode on the snapshot controls effective
    delivery and the soft differ warning.

    FULFILLMENT_SOURCE_V1: PICKUP never surfaces a delivery address or the
    address-differs warning here — Lieferadresse is not applicable to an
    Abholung, regardless of what is stored on the Inquiry snapshot (storage
    is left untouched; only this customer-facing projection suppresses it).
    """
    snapshot = inquiry.customer_snapshot if inquiry is not None else None
    name, email = _name_and_email(snapshot)
    company_name, phone = _company_and_phone(snapshot)
    invoice, delivery, differs = _resolve_addresses(
        snapshot,
        invoice_override=invoice_address,
        delivery_override=delivery_address,
        fulfillment_mode=fulfillment_mode,
    )
    warnings: tuple[CustomerDocumentWarning, ...] = (
        (WARNING_DELIVERY_ADDRESS_DIFFERS,) if differs else ()
    )
    return CustomerDocumentRecipient(
        name=name,
        email=email,
        company_name=company_name,
        phone=phone,
        invoice_address=invoice,
        delivery_address=delivery,
        delivery_address_differs=differs,
        warnings=warnings,
    )


def _resolve_addresses(
    snapshot: InquiryCustomerSnapshot | None,
    *,
    invoice_override: CustomerAddress | None,
    delivery_override: CustomerAddress | None,
    fulfillment_mode: FulfillmentMode = "UNKNOWN",
) -> tuple[CustomerAddress | None, CustomerAddress | None, bool]:
    """Resolve invoice/delivery/differs from snapshot mode (or test overrides)."""
    # Explicit kwargs (both provided as non-default path): legacy test override
    # when caller passes addresses without putting them on the snapshot.
    if invoice_override is not None or delivery_override is not None:
        # If either override is passed, use overrides exclusively for address
        # slots (tests). Mode is ignored in that case.
        invoice = invoice_override
        delivery = delivery_override
        if fulfillment_mode == "PICKUP":
            return invoice, None, False
        differs = (
            invoice is not None
            and delivery is not None
            and not customer_addresses_equal(invoice, delivery)
        )
        return invoice, delivery, differs

    if snapshot is None:
        return None, None, False
    invoice = snapshot.invoice_address
    if fulfillment_mode == "PICKUP":
        # Abholung: Rechnungsadresse still applies, Lieferadresse does not —
        # not derived from delivery_address_mode, storage stays untouched.
        return invoice, None, False
    mode = snapshot.delivery_address_mode
    if mode == "UNKNOWN":
        return invoice, None, False
    if mode == "SAME_AS_INVOICE":
        return invoice, invoice, False
    delivery = snapshot.delivery_address
    differs = (
        invoice is not None
        and delivery is not None
        and not customer_addresses_equal(invoice, delivery)
    )
    return invoice, delivery, differs


def build_customer_document_projection(
    *,
    document_type: DocumentType,
    document_id: str,
    created_at: datetime,
    order_version: OrderVersion,
    commercial_snapshot: OrderCommercialSnapshot,
    recipient: CustomerDocumentRecipient,
    fulfillment_mode: FulfillmentMode = "UNKNOWN",
) -> CustomerDocumentProjection:
    """Assemble a frozen customer-document projection from value objects."""
    if commercial_snapshot.order_id != order_version.order_id:
        raise ValueError(
            "commercial snapshot order_id does not match order version "
            f"({commercial_snapshot.order_id!r} != {order_version.order_id!r})"
        )
    positions = tuple(
        _map_position(position, order_version.guest_count_estimate)
        for position in commercial_snapshot.positions
    )
    return CustomerDocumentProjection(
        document_type=document_type,
        document_id=document_id,
        created_at=created_at,
        recipient=recipient,
        commercial_reference=CustomerDocumentCommercialReference(
            snapshot_id=commercial_snapshot.snapshot_id,
            source_offer_id=commercial_snapshot.source_offer_id,
            source_offer_version_id=commercial_snapshot.source_offer_version_id,
            variant_label=commercial_snapshot.variant_label,
        ),
        event=CustomerDocumentEvent(
            order_id=order_version.order_id,
            order_version_id=order_version.order_version_id,
            version_number=order_version.version_number,
            event_date=order_version.event_date,
            time_window_text=order_version.time_window_text,
            location_text=order_version.location_text,
            guest_count_estimate=order_version.guest_count_estimate,
            planning_mode=order_version.planning_mode,
        ),
        positions=positions,
        payment_method=commercial_snapshot.payment_method,
        payment_customer_visible_text=commercial_snapshot.payment_customer_visible_text,
        net_total_cents=sum(p.net_total_cents for p in positions),
        vat_total_cents=sum(p.vat_amount_cents for p in positions),
        gross_total_cents=sum(p.gross_total_cents for p in positions),
        fulfillment_mode=fulfillment_mode,
    )


def _name_and_email(
    snapshot: InquiryCustomerSnapshot | None,
) -> tuple[str, str | None]:
    if snapshot is None or snapshot.is_empty():
        return "Kunde", None
    name = (snapshot.contact_name or snapshot.company_name or "Kunde").strip()
    if not name:
        name = "Kunde"
    return name, snapshot.email


def _company_and_phone(
    snapshot: InquiryCustomerSnapshot | None,
) -> tuple[str | None, str | None]:
    if snapshot is None or snapshot.is_empty():
        return None, None
    company = (snapshot.company_name or "").strip() or None
    phone = (snapshot.phone or "").strip() or None
    return company, phone


def _map_position(
    position: OrderCommercialPosition,
    guest_count_estimate: int | None,
) -> CustomerDocumentPosition:
    return CustomerDocumentPosition(
        position_id=position.position_id,
        kind=position.kind,
        name=position.name,
        description=position.description,
        composition=position.composition,
        quantity=format_quantity_display(position, guest_count_estimate),
        unit_label=position.unit_label,
        unit_net_cents=position.unit_net_cents,
        net_total_cents=position.net_total_cents,
        vat_rate_percent=position.vat_rate_percent,
        vat_amount_cents=position.vat_amount_cents,
        gross_total_cents=position.gross_total_cents,
        related_position_id=position.related_position_id,
    )


class CustomerDocumentProjectionService:
    """Factory over pure CDP builders for document consumers (Confirmation, …)."""

    def build(
        self,
        *,
        document_type: DocumentType,
        document_id: str,
        created_at: datetime,
        order_version: OrderVersion,
        commercial_snapshot: OrderCommercialSnapshot,
        inquiry: Inquiry | None,
        invoice_address: CustomerAddress | None = None,
        delivery_address: CustomerAddress | None = None,
    ) -> CustomerDocumentProjection:
        fulfillment_mode = (
            inquiry.fulfillment_mode if inquiry is not None else "UNKNOWN"
        )
        recipient = build_customer_document_recipient(
            inquiry,
            invoice_address=invoice_address,
            delivery_address=delivery_address,
            fulfillment_mode=fulfillment_mode,
        )
        return build_customer_document_projection(
            document_type=document_type,
            document_id=document_id,
            created_at=created_at,
            order_version=order_version,
            commercial_snapshot=commercial_snapshot,
            recipient=recipient,
            fulfillment_mode=fulfillment_mode,
        )
