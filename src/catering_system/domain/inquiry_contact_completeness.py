"""Canonical inquiry contact-completeness gate (INQUIRY_CONTACT_COMPLETENESS_V1).

Operational truth is Inquiry.customer_snapshot (structured email/phone), never
the labelled intake_message text. A complete inquiry has both a valid e-mail
and a valid phone; name and company stay optional. Missing fields may be
appended exactly once (append-only completion) — stored values are never
replaced.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from catering_system.domain.phone_normalization import normalize_phone

if TYPE_CHECKING:
    from catering_system.domain.inquiry import Inquiry
    from catering_system.domain.inquiry_customer_snapshot import (
        InquiryCustomerSnapshot,
    )

InquiryContactCompleteness = Literal[
    "complete",
    "missing_email",
    "missing_phone",
    "missing_email_and_phone",
]

ContactField = Literal["email", "phone"]

# Office next action shown while contacts are incomplete (pack §8).
CONTACT_COMPLETION_NEXT_ACTION = "Kontaktdaten vervollständigen"

CONTACT_COMPLETENESS_BLOCKER_TEXTS: dict[str, str] = {
    "missing_email": "E-Mail-Adresse fehlt",
    "missing_phone": "Telefonnummer fehlt",
    "missing_email_and_phone": "E-Mail-Adresse und Telefonnummer fehlen",
}


def normalize_contact_email(raw: str | None) -> str:
    """Same rule as intake_contact.normalize_email — kept here so the domain
    gate has no import path back into the intake package."""
    value = (raw or "").strip()
    if not value or "@" not in value:
        return ""
    return value.casefold()


def validate_contact_email(raw: str) -> str:
    if not isinstance(raw, str):
        raise TypeError("contact email must be a str")
    normalized = normalize_contact_email(raw)
    if not normalized:
        raise ValueError("contact email is empty or invalid")
    return normalized


def validate_contact_phone(raw: str) -> str:
    if not isinstance(raw, str):
        raise TypeError("contact phone must be a str")
    normalized = normalize_phone(raw)
    if not normalized:
        raise ValueError("contact phone is empty or invalid")
    return normalized


def _has_valid_email(snapshot: "InquiryCustomerSnapshot | None") -> bool:
    return snapshot is not None and bool(normalize_contact_email(snapshot.email))


def _has_valid_phone(snapshot: "InquiryCustomerSnapshot | None") -> bool:
    return snapshot is not None and bool(normalize_phone(snapshot.phone))


def derive_contact_completeness(
    snapshot: "InquiryCustomerSnapshot | None",
) -> InquiryContactCompleteness:
    has_email = _has_valid_email(snapshot)
    has_phone = _has_valid_phone(snapshot)
    if has_email and has_phone:
        return "complete"
    if has_email:
        return "missing_phone"
    if has_phone:
        return "missing_email"
    return "missing_email_and_phone"


def derive_inquiry_contact_completeness(
    inquiry: "Inquiry",
) -> InquiryContactCompleteness:
    return derive_contact_completeness(inquiry.customer_snapshot)


def missing_contact_fields(
    completeness: InquiryContactCompleteness,
) -> tuple[ContactField, ...]:
    if completeness == "complete":
        return ()
    if completeness == "missing_email":
        return ("email",)
    if completeness == "missing_phone":
        return ("phone",)
    return ("email", "phone")


def inquiry_contact_complete(inquiry: "Inquiry") -> bool:
    return derive_inquiry_contact_completeness(inquiry) == "complete"


def contact_completeness_blocker_text(
    completeness: InquiryContactCompleteness,
) -> str | None:
    return CONTACT_COMPLETENESS_BLOCKER_TEXTS.get(completeness)


def complete_inquiry_contact_information(
    inquiry: "Inquiry",
    *,
    email: str | None = None,
    phone: str | None = None,
) -> "Inquiry":
    """Append-only completion: fill missing snapshot email/phone exactly once.

    - a stored non-empty value is never replaced (conflicting input raises);
    - an identical resubmission is idempotent (returns the inquiry unchanged);
    - contact_name/company_name are preserved untouched;
    - invoice_address/delivery_address/delivery_address_mode are preserved
      untouched (CUSTOMER_ADDRESS_SOURCE_V1-B);
    - the result is a new frozen snapshot value object.
    """
    from dataclasses import replace as dataclass_replace

    from catering_system.domain.inquiry_customer_snapshot import (
        InquiryCustomerSnapshot,
    )

    if email is None and phone is None:
        raise ValueError("contact completion requires email or phone")

    snapshot = inquiry.customer_snapshot
    current_email = (snapshot.email or "").strip() if snapshot is not None else ""
    current_phone = (snapshot.phone or "").strip() if snapshot is not None else ""

    next_email = current_email or None
    if email is not None:
        normalized_email = validate_contact_email(email)
        if current_email:
            if normalize_contact_email(current_email) != normalized_email:
                raise ValueError("contact email already recorded and cannot change")
        else:
            next_email = normalized_email

    next_phone = current_phone or None
    if phone is not None:
        normalized_phone = validate_contact_phone(phone)
        if current_phone:
            if normalize_phone(current_phone) != normalized_phone:
                raise ValueError("contact phone already recorded and cannot change")
        else:
            next_phone = normalized_phone

    next_snapshot = InquiryCustomerSnapshot(
        company_name=snapshot.company_name if snapshot is not None else None,
        contact_name=snapshot.contact_name if snapshot is not None else None,
        email=next_email,
        phone=next_phone,
        invoice_address=snapshot.invoice_address if snapshot is not None else None,
        delivery_address=snapshot.delivery_address if snapshot is not None else None,
        delivery_address_mode=(
            snapshot.delivery_address_mode if snapshot is not None else "UNKNOWN"
        ),
    )
    if snapshot is not None and next_snapshot == snapshot:
        return inquiry
    return dataclass_replace(inquiry, customer_snapshot=next_snapshot)
