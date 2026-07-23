"""Pure customer-document create eligibility — V1-C-1.

No repositories. No Offer. No intake parsing. No HTML/PDF/email/persistence.
"""

from __future__ import annotations

from catering_system.domain.customer_document_eligibility import (
    CustomerDocumentEligibility,
    DocumentBlocker,
    sort_document_blockers,
)
from catering_system.domain.customer_document_projection import (
    CustomerDocumentRecipient,
)
from catering_system.domain.order import Order, OrderVersion
from catering_system.domain.order_commercial_snapshot import OrderCommercialSnapshot

_PLACEHOLDER_NAME = "Kunde"


def evaluate_customer_document_eligibility(
    *,
    order: Order,
    order_version: OrderVersion | None,
    commercial_snapshot: OrderCommercialSnapshot | None,
    recipient: CustomerDocumentRecipient,
) -> CustomerDocumentEligibility:
    """Decide whether a customer document may be created for this order state."""
    blockers: list[DocumentBlocker] = []

    if commercial_snapshot is None:
        blockers.append(DocumentBlocker(code="MISSING_COMMERCIAL_SNAPSHOT"))

    if _invalid_order_state(order, order_version):
        blockers.append(DocumentBlocker(code="INVALID_ORDER_STATE"))

    if not _has_usable_name(recipient):
        blockers.append(DocumentBlocker(code="MISSING_CUSTOMER_NAME"))

    if not _has_usable_contact(recipient):
        blockers.append(DocumentBlocker(code="MISSING_CUSTOMER_CONTACT"))

    ordered = sort_document_blockers(tuple(blockers))
    return CustomerDocumentEligibility(allowed=not ordered, blockers=ordered)


def _invalid_order_state(order: Order, order_version: OrderVersion | None) -> bool:
    if order.cancelled_at is not None:
        return True
    if order.effective_order_version_id is None:
        return True
    if order_version is None:
        return True
    if order_version.order_id != order.order_id:
        return True
    if order_version.order_version_id != order.effective_order_version_id:
        return True
    if order.candidate_order_version_id is not None:
        return True
    if order_version.kitchen_print_confirmed_at is None:
        return True
    return False


def _has_usable_name(recipient: CustomerDocumentRecipient) -> bool:
    name = recipient.name.strip()
    if name and name != _PLACEHOLDER_NAME:
        return True
    company = (recipient.company_name or "").strip()
    return bool(company)


def _has_usable_contact(recipient: CustomerDocumentRecipient) -> bool:
    email = (recipient.email or "").strip()
    phone = (recipient.phone or "").strip()
    return bool(email) or bool(phone)
