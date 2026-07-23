"""Immutable inquiry customer snapshot — historical contact fact at link/create time.

CUSTOMER_ADDRESS_SOURCE_V1-A: invoice/delivery addresses + delivery_address_mode.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, cast

from catering_system.domain.customer_document_projection import (
    CustomerAddress,
    canonicalize_customer_address,
)
from catering_system.intake.intake_contact import (
    labelled_intake_context,
    normalize_email,
)
from catering_system.domain.phone_normalization import normalize_phone

if TYPE_CHECKING:
    from catering_system.domain.inquiry import Inquiry

DeliveryAddressMode = Literal["UNKNOWN", "SAME_AS_INVOICE", "SEPARATE"]
DELIVERY_ADDRESS_MODES: tuple[DeliveryAddressMode, ...] = (
    "UNKNOWN",
    "SAME_AS_INVOICE",
    "SEPARATE",
)
_DELIVERY_ADDRESS_MODE_SET: frozenset[str] = frozenset(DELIVERY_ADDRESS_MODES)


@dataclass(frozen=True)
class InquiryCustomerSnapshot:
    """Frozen contact snapshot stored on Inquiry; not a live CustomerIdentity projection."""

    company_name: str | None = None
    contact_name: str | None = None
    email: str | None = None
    phone: str | None = None
    invoice_address: CustomerAddress | None = None
    delivery_address: CustomerAddress | None = None
    delivery_address_mode: DeliveryAddressMode = "UNKNOWN"

    def __post_init__(self) -> None:
        if self.delivery_address_mode not in _DELIVERY_ADDRESS_MODE_SET:
            raise ValueError(
                f"unsupported delivery_address_mode: {self.delivery_address_mode!r}"
            )
        invoice = canonicalize_customer_address(self.invoice_address)
        delivery = canonicalize_customer_address(self.delivery_address)
        if invoice is not self.invoice_address:
            object.__setattr__(self, "invoice_address", invoice)
        if delivery is not self.delivery_address:
            object.__setattr__(self, "delivery_address", delivery)
        if self.delivery_address_mode in {"UNKNOWN", "SAME_AS_INVOICE"}:
            if self.delivery_address is not None:
                raise ValueError(
                    "delivery_address must be None when mode is "
                    f"{self.delivery_address_mode}"
                )
        elif self.delivery_address is None:
            raise ValueError("SEPARATE mode requires delivery_address")

    def is_empty(self) -> bool:
        """Contact-only emptiness for completeness gates (addresses ignored)."""
        return not any(
            value
            for value in (
                self.company_name,
                self.contact_name,
                self.email,
                self.phone,
            )
        )

    def has_persisted_facts(self) -> bool:
        """True when snapshot should be stored (contact and/or address facts)."""
        return (
            not self.is_empty()
            or self.invoice_address is not None
            or self.delivery_address_mode != "UNKNOWN"
        )


def validate_delivery_address_mode(value: str) -> DeliveryAddressMode:
    if value not in _DELIVERY_ADDRESS_MODE_SET:
        raise ValueError(f"unsupported delivery_address_mode: {value!r}")
    return cast(DeliveryAddressMode, value)


def set_inquiry_customer_addresses(
    inquiry: "Inquiry",
    *,
    invoice_address: CustomerAddress | None,
    delivery_address: CustomerAddress | None,
    delivery_address_mode: DeliveryAddressMode | str,
) -> "Inquiry":
    """Replace snapshot address facts; preserve contact fields untouched.

    UNKNOWN / SAME_AS_INVOICE store delivery_address as None (any provided
    delivery is ignored). SEPARATE requires a non-null delivery_address —
    validated by InquiryCustomerSnapshot invariants.
    """
    from dataclasses import replace as dataclass_replace

    from catering_system.domain.inquiry import Inquiry as _Inquiry

    if not isinstance(inquiry, _Inquiry):
        raise TypeError("inquiry must be an Inquiry")
    if not isinstance(delivery_address_mode, str):
        raise TypeError("delivery_address_mode must be a str")
    mode = validate_delivery_address_mode(delivery_address_mode)
    stored_delivery = (
        None if mode in {"UNKNOWN", "SAME_AS_INVOICE"} else delivery_address
    )
    snapshot = inquiry.customer_snapshot
    next_snapshot = InquiryCustomerSnapshot(
        company_name=snapshot.company_name if snapshot is not None else None,
        contact_name=snapshot.contact_name if snapshot is not None else None,
        email=snapshot.email if snapshot is not None else None,
        phone=snapshot.phone if snapshot is not None else None,
        invoice_address=invoice_address,
        delivery_address=stored_delivery,
        delivery_address_mode=mode,
    )
    if snapshot is not None and next_snapshot == snapshot:
        return inquiry
    return dataclass_replace(inquiry, customer_snapshot=next_snapshot)


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
    if not snapshot.has_persisted_facts():
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
    if not snapshot.has_persisted_facts():
        return None
    return snapshot


def customer_address_to_mapping(
    address: CustomerAddress | None,
) -> dict[str, str | None] | None:
    if address is None:
        return None
    return {
        "street": address.street,
        "postal_code": address.postal_code,
        "city": address.city,
        "country": address.country,
    }


def customer_address_from_mapping(
    data: object | None,
) -> CustomerAddress | None:
    if data is None:
        return None
    if not isinstance(data, dict) or not all(isinstance(k, str) for k in data):
        raise TypeError("address must be an object or null")
    allowed = {"street", "postal_code", "city", "country"}
    if set(data) != allowed:
        raise ValueError(
            "address object keys must be exactly street/postal_code/city/country"
        )
    return canonicalize_customer_address(
        CustomerAddress(
            street=_optional_str(data.get("street")),
            postal_code=_optional_str(data.get("postal_code")),
            city=_optional_str(data.get("city")),
            country=_optional_str(data.get("country")),
        )
    )


def customer_snapshot_to_mapping(
    snapshot: InquiryCustomerSnapshot | None,
) -> dict[str, object] | None:
    if snapshot is None:
        return None
    return {
        "company_name": snapshot.company_name,
        "contact_name": snapshot.contact_name,
        "email": snapshot.email,
        "phone": snapshot.phone,
        "invoice_address": customer_address_to_mapping(snapshot.invoice_address),
        "delivery_address": customer_address_to_mapping(snapshot.delivery_address),
        "delivery_address_mode": snapshot.delivery_address_mode,
    }


def customer_snapshot_from_mapping(
    data: dict[str, object] | None,
) -> InquiryCustomerSnapshot | None:
    if data is None:
        return None
    mode_raw = data.get("delivery_address_mode")
    if mode_raw is None:
        mode: DeliveryAddressMode = "UNKNOWN"
    else:
        if not isinstance(mode_raw, str):
            raise TypeError("delivery_address_mode must be a str or null")
        mode = validate_delivery_address_mode(mode_raw)
    snapshot = InquiryCustomerSnapshot(
        company_name=_optional_str(data.get("company_name")),
        contact_name=_optional_str(data.get("contact_name")),
        email=_optional_str(data.get("email")),
        phone=_optional_str(data.get("phone")),
        invoice_address=customer_address_from_mapping(data.get("invoice_address")),
        delivery_address=customer_address_from_mapping(data.get("delivery_address")),
        delivery_address_mode=mode,
    )
    if not snapshot.has_persisted_facts():
        return None
    return snapshot


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("snapshot fields must be str or null")
    trimmed = value.strip()
    return trimmed or None
