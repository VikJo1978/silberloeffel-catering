"""Live customer-document preview — CUSTOMER_DOCUMENT_PROJECTION_V1-D.

Assembles CustomerDocumentPreview from Projection builders + Eligibility.
No persistence. No Offer. No intake parsing. No PDF/HTML/email.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime

from catering_system.domain.customer_document_preview import CustomerDocumentPreview
from catering_system.domain.customer_document_projection import (
    WARNING_DELIVERY_ADDRESS_DIFFERS,
    CustomerAddress,
    CustomerDocumentEvent,
    CustomerDocumentRecipient,
    customer_addresses_equal,
)
from catering_system.domain.inquiry import FulfillmentMode, Inquiry
from catering_system.domain.order import Order, OrderVersion
from catering_system.domain.order_commercial_snapshot import OrderCommercialSnapshot
from catering_system.domain.order_payment_reminder import OrderPaymentReminder
from catering_system.repositories.inquiry_repository import InquiryRepository
from catering_system.repositories.order_commercial_snapshot_repository import (
    OrderCommercialSnapshotRepository,
)
from catering_system.repositories.order_repository import OrderRepository
from catering_system.repositories.payment_reminder_repository import (
    PaymentReminderRepository,
)
from catering_system.services.customer_document_eligibility import (
    evaluate_customer_document_eligibility,
)
from catering_system.services.customer_document_projection import (
    build_customer_document_projection,
    build_customer_document_recipient,
    resolve_document_payment,
)

_PREVIEW_DOCUMENT_ID = "preview"


class CustomerDocumentPreviewNotFoundError(LookupError):
    """Raised when the order for a live preview does not exist."""


def build_customer_document_preview(
    *,
    order: Order,
    order_version: OrderVersion | None,
    commercial_snapshot: OrderCommercialSnapshot | None,
    recipient_inquiry: Inquiry | None,
    invoice_address: CustomerAddress | None = None,
    delivery_address: CustomerAddress | None = None,
    payment_reminder: OrderPaymentReminder | None = None,
    now: datetime | None = None,
    recipient_override: CustomerDocumentRecipient | None = None,
) -> CustomerDocumentPreview:
    """Pure assemble of live preview facts + eligibility (no repos)."""
    fulfillment_mode: FulfillmentMode = (
        recipient_inquiry.fulfillment_mode
        if recipient_inquiry is not None
        else "UNKNOWN"
    )
    recipient = recipient_override or build_customer_document_recipient(
        recipient_inquiry,
        invoice_address=invoice_address,
        delivery_address=delivery_address,
        fulfillment_mode=fulfillment_mode,
    )
    eligibility = evaluate_customer_document_eligibility(
        order=order,
        order_version=order_version,
        commercial_snapshot=commercial_snapshot,
        recipient=recipient,
        fulfillment_mode=fulfillment_mode,
    )
    event = _event_from_version(order_version)
    if commercial_snapshot is not None and order_version is not None:
        payment_method, payment_customer_visible_text = resolve_document_payment(
            commercial_snapshot, payment_reminder
        )
        projection = build_customer_document_projection(
            document_type="ORDER_CONFIRMATION",
            document_id=_PREVIEW_DOCUMENT_ID,
            created_at=now or datetime.now(UTC),
            order_version=order_version,
            commercial_snapshot=commercial_snapshot,
            recipient=recipient,
            fulfillment_mode=fulfillment_mode,
            payment_method=payment_method,
            payment_customer_visible_text=payment_customer_visible_text,
        )
        return CustomerDocumentPreview(
            document_type="ORDER_CONFIRMATION",
            eligible=eligibility.allowed,
            warnings=projection.recipient.warnings,
            blockers=eligibility.blockers,
            recipient=projection.recipient,
            event=projection.event,
            commercial_reference=projection.commercial_reference,
            positions=projection.positions,
            payment_method=projection.payment_method,
            payment_customer_visible_text=projection.payment_customer_visible_text,
            net_total_cents=projection.net_total_cents,
            vat_total_cents=projection.vat_total_cents,
            gross_total_cents=projection.gross_total_cents,
            fulfillment_mode=projection.fulfillment_mode,
        )
    return CustomerDocumentPreview(
        document_type="ORDER_CONFIRMATION",
        eligible=eligibility.allowed,
        warnings=recipient.warnings,
        blockers=eligibility.blockers,
        recipient=recipient,
        event=event,
        commercial_reference=None,
        positions=(),
        payment_method=None,
        payment_customer_visible_text=None,
        net_total_cents=None,
        vat_total_cents=None,
        gross_total_cents=None,
        fulfillment_mode=fulfillment_mode,
    )


def _event_from_version(
    order_version: OrderVersion | None,
) -> CustomerDocumentEvent | None:
    if order_version is None:
        return None
    return CustomerDocumentEvent(
        order_id=order_version.order_id,
        order_version_id=order_version.order_version_id,
        version_number=order_version.version_number,
        event_date=order_version.event_date,
        time_window_text=order_version.time_window_text,
        location_text=order_version.location_text,
        guest_count_estimate=order_version.guest_count_estimate,
        planning_mode=order_version.planning_mode,
    )


def _recipient_for_order_version(
    orders: OrderRepository,
    inquiry: Inquiry | None,
    version: OrderVersion | None,
    *,
    invoice_address: CustomerAddress | None,
    delivery_address: CustomerAddress | None,
    fulfillment_mode: FulfillmentMode,
) -> CustomerDocumentRecipient:
    recipient = build_customer_document_recipient(
        inquiry,
        invoice_address=invoice_address,
        delivery_address=delivery_address,
        fulfillment_mode=fulfillment_mode,
    )
    if invoice_address is not None or delivery_address is not None:
        return recipient
    if version is None:
        return recipient
    context = orders.get_operational_context(version.order_version_id)
    if context is None:
        return recipient
    if version.parent_order_version_id is None and context.delivery_address is None:
        return recipient
    exact_delivery = None if fulfillment_mode == "PICKUP" else context.delivery_address
    differs = (
        recipient.invoice_address is not None
        and exact_delivery is not None
        and not customer_addresses_equal(recipient.invoice_address, exact_delivery)
    )
    warnings = (WARNING_DELIVERY_ADDRESS_DIFFERS,) if differs else ()
    return replace(
        recipient,
        delivery_address=exact_delivery,
        delivery_address_differs=differs,
        warnings=warnings,
    )


class CustomerDocumentPreviewService:
    """Load order truth and build a live confirmation preview."""

    def __init__(
        self,
        order_repository: OrderRepository,
        inquiry_repository: InquiryRepository,
        commercial_snapshot_repository: OrderCommercialSnapshotRepository,
        *,
        payment_reminder_repository: PaymentReminderRepository | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._orders = order_repository
        self._inquiries = inquiry_repository
        self._commercial_snapshots = commercial_snapshot_repository
        self._payment_reminders = payment_reminder_repository
        self._now = now or (lambda: datetime.now(UTC))

    def preview_order_confirmation(
        self,
        order_id: str,
        *,
        invoice_address: CustomerAddress | None = None,
        delivery_address: CustomerAddress | None = None,
    ) -> CustomerDocumentPreview:
        order = self._orders.get_order(order_id)
        if order is None:
            raise CustomerDocumentPreviewNotFoundError(order_id)
        version: OrderVersion | None = None
        if order.effective_order_version_id is not None:
            version = self._orders.get_order_version(order.effective_order_version_id)
        commercial = self._commercial_snapshots.get_by_order_id(order.order_id)
        inquiry = self._inquiries.get_by_id(order.source_inquiry_id)
        fulfillment_mode: FulfillmentMode = (
            inquiry.fulfillment_mode if inquiry is not None else "UNKNOWN"
        )
        recipient = _recipient_for_order_version(
            self._orders,
            inquiry,
            version,
            invoice_address=invoice_address,
            delivery_address=delivery_address,
            fulfillment_mode=fulfillment_mode,
        )
        payment_reminder = (
            self._payment_reminders.get(order.order_id)
            if self._payment_reminders is not None
            else None
        )
        return build_customer_document_preview(
            order=order,
            order_version=version,
            commercial_snapshot=commercial,
            recipient_inquiry=inquiry,
            invoice_address=invoice_address,
            delivery_address=delivery_address,
            payment_reminder=payment_reminder,
            now=self._now(),
            recipient_override=recipient,
        )
