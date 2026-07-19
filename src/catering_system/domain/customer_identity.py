"""Customer identity foundation — not a CRM aggregate."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, cast

from catering_system.domain.phone_normalization import normalize_phone_for_contact_point

CustomerIdentityStatus = Literal["active", "inactive", "merged"]
CUSTOMER_IDENTITY_STATUSES: tuple[CustomerIdentityStatus, ...] = (
    "active",
    "inactive",
    "merged",
)
CUSTOMER_IDENTITY_STATUS_SET: frozenset[str] = frozenset(CUSTOMER_IDENTITY_STATUSES)
ACTIVE_CUSTOMER_IDENTITY_STATUS: CustomerIdentityStatus = "active"

PhoneContactPointStatus = Literal["active", "inactive"]
PHONE_CONTACT_POINT_STATUSES: tuple[PhoneContactPointStatus, ...] = (
    "active",
    "inactive",
)
PHONE_CONTACT_POINT_STATUS_SET: frozenset[str] = frozenset(PHONE_CONTACT_POINT_STATUSES)
ACTIVE_PHONE_CONTACT_POINT_STATUS: PhoneContactPointStatus = "active"


def validate_customer_identity_status(value: str) -> CustomerIdentityStatus:
    if value not in CUSTOMER_IDENTITY_STATUS_SET:
        raise ValueError(
            "customer identity status must be one of "
            f"{sorted(CUSTOMER_IDENTITY_STATUS_SET)}, got {value!r}"
        )
    return cast(CustomerIdentityStatus, value)


def validate_phone_contact_point_status(value: str) -> PhoneContactPointStatus:
    if value not in PHONE_CONTACT_POINT_STATUS_SET:
        raise ValueError(
            "phone contact point status must be one of "
            f"{sorted(PHONE_CONTACT_POINT_STATUS_SET)}, got {value!r}"
        )
    return cast(PhoneContactPointStatus, value)


def _require_aware_timestamp(field_name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


@dataclass(frozen=True)
class CustomerIdentity:
    customer_id: str
    display_name: str
    company_name: str | None
    status: CustomerIdentityStatus
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class PhoneContactPoint:
    phone_contact_point_id: str
    customer_id: str
    normalized_phone: str
    display_phone: str | None
    status: PhoneContactPointStatus
    created_at: datetime
    updated_at: datetime
    valid_from: datetime | None = None
    valid_to: datetime | None = None


def validate_customer_identity(identity: CustomerIdentity) -> CustomerIdentity:
    if not identity.customer_id.strip():
        raise ValueError("customer_id must not be empty")
    if not identity.display_name.strip():
        raise ValueError("display_name must not be empty")
    validate_customer_identity_status(identity.status)
    _require_aware_timestamp("created_at", identity.created_at)
    _require_aware_timestamp("updated_at", identity.updated_at)
    return identity


def validate_phone_contact_point(point: PhoneContactPoint) -> PhoneContactPoint:
    if not point.phone_contact_point_id.strip():
        raise ValueError("phone_contact_point_id must not be empty")
    if not point.customer_id.strip():
        raise ValueError("customer_id must not be empty")
    normalized = normalize_phone_for_contact_point(point.normalized_phone)
    if normalized != point.normalized_phone:
        raise ValueError("normalized_phone must already be canonical")
    validate_phone_contact_point_status(point.status)
    _require_aware_timestamp("created_at", point.created_at)
    _require_aware_timestamp("updated_at", point.updated_at)
    if point.valid_from is not None:
        _require_aware_timestamp("valid_from", point.valid_from)
    if point.valid_to is not None:
        _require_aware_timestamp("valid_to", point.valid_to)
    if (
        point.valid_from is not None
        and point.valid_to is not None
        and point.valid_to < point.valid_from
    ):
        raise ValueError("valid_to must not be earlier than valid_from")
    return point
