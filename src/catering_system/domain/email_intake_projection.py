"""Email intake read projection — derived from email-source inquiries only."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from catering_system.domain.contact_projection import derive_contact_identity
from catering_system.domain.inquiry import CrmStage, Inquiry
from catering_system.domain.offer import Offer
from catering_system.domain.order import Order
from catering_system.intake.intake_contact import parse_intake_contact


@dataclass(frozen=True)
class EmailIntakeProjection:
    """Office-facing email intake row; projection-only, not a Core entity."""

    email_id: str
    inquiry_id: str
    contact_key: str
    sender_name: str | None
    sender_email: str | None
    subject: str | None
    preview: str | None
    crm_stage: CrmStage
    received_at: datetime
    external_ref: str | None
    linked_offer_id: str | None
    linked_order_ids: tuple[str, ...]


def email_intake_subject(inquiry: Inquiry) -> str | None:
    """Return intake_subject only — never fabricate from other inquiry fields."""

    subject = (inquiry.intake_subject or "").strip()
    return subject or None


def email_intake_preview(inquiry: Inquiry) -> str | None:
    """Return intake_message only — never fabricate from other inquiry fields."""

    message = (inquiry.intake_message or "").strip()
    return message or None


def project_email_intake(
    inquiry: Inquiry,
    *,
    offer: Offer | None,
    orders: list[Order],
) -> EmailIntakeProjection:
    contact_key, _identity_source = derive_contact_identity(inquiry)
    parsed = parse_intake_contact(inquiry)
    return EmailIntakeProjection(
        email_id=inquiry.inquiry_id,
        inquiry_id=inquiry.inquiry_id,
        contact_key=contact_key,
        sender_name=parsed["display_name"],
        sender_email=parsed["email"],
        subject=email_intake_subject(inquiry),
        preview=email_intake_preview(inquiry),
        crm_stage=inquiry.crm_stage,
        received_at=inquiry.created_at,
        external_ref=inquiry.intake_external_ref,
        linked_offer_id=offer.offer_id if offer is not None else None,
        linked_order_ids=tuple(order.order_id for order in orders),
    )
