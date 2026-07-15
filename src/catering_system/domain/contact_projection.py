"""Contact read projection — derived identity, never persisted as CRM truth."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from catering_system.domain.inquiry import Inquiry
from catering_system.intake.intake_contact import parse_intake_contact

ContactIdentitySource = Literal[
    "linkage_contact",
    "linkage_customer",
    "intake_email",
    "intake_phone",
    "inquiry",
]


@dataclass(frozen=True)
class ContactProjection:
    """Office-facing contact aggregate; projection-only, not a Core entity."""

    contact_key: str
    identity_source: ContactIdentitySource
    display_name: str
    email: str | None
    phone: str | None
    inquiry_count: int
    open_inquiries: int
    active_orders: int
    last_activity: datetime
    inquiry_ids: tuple[str, ...] = field(default_factory=tuple)


def derive_contact_identity(inquiry: Inquiry) -> tuple[str, ContactIdentitySource]:
    linkage = inquiry.customer_linkage
    contact_id = linkage.get("contact_id")
    if isinstance(contact_id, str) and contact_id.strip():
        return f"linkage:contact:{contact_id.strip()}", "linkage_contact"
    customer_id = linkage.get("customer_id")
    if isinstance(customer_id, str) and customer_id.strip():
        return f"linkage:customer:{customer_id.strip()}", "linkage_customer"

    parsed = parse_intake_contact(inquiry)
    email = parsed["email"]
    if email:
        return f"intake:email:{email}", "intake_email"
    phone = parsed["phone"]
    if phone:
        return f"intake:phone:{phone}", "intake_phone"
    return f"inquiry:{inquiry.inquiry_id}", "inquiry"
