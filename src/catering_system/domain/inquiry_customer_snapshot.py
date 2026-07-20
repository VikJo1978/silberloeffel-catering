"""Immutable inquiry customer snapshot — historical contact fact at link/create time."""

from __future__ import annotations

from dataclasses import dataclass

from catering_system.intake.intake_contact import (
    labelled_intake_context,
    normalize_email,
)
from catering_system.domain.phone_normalization import normalize_phone


@dataclass(frozen=True)
class InquiryCustomerSnapshot:
    """Frozen contact snapshot stored on Inquiry; not a live CustomerIdentity projection."""

    company_name: str | None = None
    contact_name: str | None = None
    email: str | None = None
    phone: str | None = None

    def is_empty(self) -> bool:
        return not any(
            value
            for value in (
                self.company_name,
                self.contact_name,
                self.email,
                self.phone,
            )
        )


def validate_customer_id_reference(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("customer_id must be a str")
    trimmed = value.strip()
    if not trimmed:
        raise ValueError("customer_id must not be empty")
    return trimmed


def snapshot_from_intake_message(
    intake_message: str | None,
    *,
    intake_subject: str | None = None,
) -> InquiryCustomerSnapshot | None:
    """Build snapshot from labelled intake context only; never auto-match CustomerIdentity."""
    labelled, _remaining = labelled_intake_context(intake_message)
    company = (labelled.get("Firma") or "").strip() or None
    contact = (labelled.get("Name") or "").strip() or None
    email = normalize_email(labelled.get("E-Mail")) or None
    phone = normalize_phone(labelled.get("Telefon")) or None
    snapshot = InquiryCustomerSnapshot(
        company_name=company,
        contact_name=contact,
        email=email,
        phone=phone,
    )
    if snapshot.is_empty():
        return None
    return snapshot


def snapshot_from_structured_contact(
    *,
    contact_email: str | None = None,
    contact_phone: str | None = None,
    contact_name: str | None = None,
    company_name: str | None = None,
    intake_message: str | None = None,
    intake_subject: str | None = None,
) -> InquiryCustomerSnapshot | None:
    """Structured create/update contract (INQUIRY_CONTACT_COMPLETENESS_V1 §6).

    Structured fields are operational truth; the labelled intake_message text
    stays a compatibility fallback that only fills fields the structured
    input did not provide. Structured email/phone are validated strictly —
    an invalid value raises instead of being silently dropped.
    """
    from catering_system.domain.inquiry_contact_completeness import (
        validate_contact_email,
        validate_contact_phone,
    )

    fallback = snapshot_from_intake_message(
        intake_message, intake_subject=intake_subject
    )
    email = (
        validate_contact_email(contact_email)
        if contact_email is not None and contact_email.strip()
        else (fallback.email if fallback is not None else None)
    )
    phone = (
        validate_contact_phone(contact_phone)
        if contact_phone is not None and contact_phone.strip()
        else (fallback.phone if fallback is not None else None)
    )
    name = _optional_str(contact_name) or (
        fallback.contact_name if fallback is not None else None
    )
    company = _optional_str(company_name) or (
        fallback.company_name if fallback is not None else None
    )
    snapshot = InquiryCustomerSnapshot(
        company_name=company,
        contact_name=name,
        email=email,
        phone=phone,
    )
    if snapshot.is_empty():
        return None
    return snapshot


def customer_snapshot_to_mapping(
    snapshot: InquiryCustomerSnapshot | None,
) -> dict[str, str | None] | None:
    if snapshot is None:
        return None
    return {
        "company_name": snapshot.company_name,
        "contact_name": snapshot.contact_name,
        "email": snapshot.email,
        "phone": snapshot.phone,
    }


def customer_snapshot_from_mapping(
    data: dict[str, object] | None,
) -> InquiryCustomerSnapshot | None:
    if data is None:
        return None
    snapshot = InquiryCustomerSnapshot(
        company_name=_optional_str(data.get("company_name")),
        contact_name=_optional_str(data.get("contact_name")),
        email=_optional_str(data.get("email")),
        phone=_optional_str(data.get("phone")),
    )
    if snapshot.is_empty():
        return None
    return snapshot


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("snapshot fields must be str or null")
    trimmed = value.strip()
    return trimmed or None
