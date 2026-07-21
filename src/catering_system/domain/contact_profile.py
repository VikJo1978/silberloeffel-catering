"""Immutable contact profiles — stable identity for office notes and aliases."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from catering_system.domain.inquiry import Inquiry
from catering_system.domain.contact_projection import derive_contact_identity
from catering_system.intake.intake_contact import parse_intake_contact

ContactProfileAliasType = Literal[
    "contact_key",
    "email",
    "phone",
    "linkage_contact",
    "linkage_customer",
    "inquiry",
]

CONTACT_PROFILE_ALIAS_TYPES: tuple[ContactProfileAliasType, ...] = (
    "contact_key",
    "email",
    "phone",
    "linkage_contact",
    "linkage_customer",
    "inquiry",
)


@dataclass(frozen=True)
class ContactProfile:
    contact_profile_id: str
    display_name: str
    email: str | None
    phone: str | None
    created_at: datetime
    updated_at: datetime
    merged_into_id: str | None = None


@dataclass(frozen=True)
class ContactProfileAlias:
    alias_type: ContactProfileAliasType
    alias_value: str
    contact_profile_id: str


def collect_inquiry_aliases(inquiry: Inquiry) -> list[tuple[ContactProfileAliasType, str]]:
    """Stable identifier aliases for one inquiry — not display-name based."""

    aliases: list[tuple[ContactProfileAliasType, str]] = []
    contact_key, _source = derive_contact_identity(inquiry)
    aliases.append(("contact_key", contact_key))

    linkage = inquiry.customer_linkage
    contact_id = linkage.get("contact_id")
    if isinstance(contact_id, str) and contact_id.strip():
        aliases.append(("linkage_contact", contact_id.strip()))
    customer_id = linkage.get("customer_id")
    if isinstance(customer_id, str) and customer_id.strip():
        aliases.append(("linkage_customer", customer_id.strip()))

    parsed = parse_intake_contact(inquiry)
    email = parsed["email"]
    if email:
        aliases.append(("email", email))
    phone = parsed["phone"]
    if phone:
        aliases.append(("phone", phone))

    aliases.append(("inquiry", inquiry.inquiry_id))
    # de-dupe while preserving order
    seen: set[tuple[str, str]] = set()
    unique: list[tuple[ContactProfileAliasType, str]] = []
    for item in aliases:
        if item in seen:
            continue
        seen.add(item)
        unique.append(item)
    return unique
