"""Live customer-document preview — CUSTOMER_DOCUMENT_PROJECTION_V1-D.

Assembles CustomerDocumentPreview from Projection builders + Eligibility.
No persistence. No Offer. No intake parsing. No PDF/HTML/email.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Callable

from catering_system.domain.customer_document_preview import CustomerDocumentPreview
from catering_system.domain.customer_document_projection import (
    CustomerAddress,
    CustomerDocumentEvent,
)
from catering_system.domain.inquiry import Inquiry
from catering_system.domain.order import Order, OrderVersion
from catering_system.domain.order_commercial_snapshot import OrderCommercialSnapshot
from catering_system.repositories.inquiry_repository import InquiryRepository
from catering_system.repositories.order_commercial_snapshot_repository import (
    OrderCommercialSnapshotRepository,
)
from catering_system.repositories.order_repository import OrderRepository
from catering_system.services.customer_document_eligibility import (
    evaluate_customer_document_eligibility,
)
from catering_system.services.customer_document_projection import (
    build_customer_document_projection,
    build_customer_document_recipient,
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
    now: datetime | None = None,
) -> CustomerDocumentPreview:
    """Pure assemble of live preview facts + eligibility (no repos)."""
    recipient = build_customer_document_recipient(
        recipient_inquiry,
        invoice_address=invoice_address,
        delivery_address=delivery_address,
    )
    eligibility = evaluate_customer_document_eligibility(
        order=order,
        order_version=order_version,
        commercial_snapshot=commercial_snapshot,
        recipient=recipient,
    )
    event = _event_from_version(order_version)
    if commercial_snapshot is not None and order_version is not None:
        projection = build_customer_document_projection(
            document_type="ORDER_CONFIRMATION",
            document_id=_PREVIEW_DOCUMENT_ID,
            created_at=now or datetime.now(UTC),
            order_version=order_version,
            commercial_snapshot=commercial_snapshot,
            recipient=recipient,
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


class CustomerDocumentPreviewService:
    """Load order truth and build a live confirmation preview."""

    def __init__(
        self,
        order_repository: OrderRepository,
        inquiry_repository: InquiryRepository,
        commercial_snapshot_repository: OrderCommercialSnapshotRepository,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._orders = order_repository
        self._inquiries = inquiry_repository
        self._commercial_snapshots = commercial_snapshot_repository
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
        return build_customer_document_preview(
            order=order,
            order_version=version,
            commercial_snapshot=commercial,
            recipient_inquiry=inquiry,
            invoice_address=invoice_address,
            delivery_address=delivery_address,
            now=self._now(),
        )
