"""Domain validation tests for customer identity foundation."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from catering_system.domain.customer_identity import (
    CustomerIdentity,
    PhoneContactPoint,
    validate_customer_identity,
    validate_phone_contact_point,
)


def _now() -> datetime:
    return datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)


def test_validate_customer_identity_requires_display_name() -> None:
    identity = CustomerIdentity(
        customer_id="cust-1",
        display_name="  ",
        company_name=None,
        status="active",
        created_at=_now(),
        updated_at=_now(),
    )
    with pytest.raises(ValueError, match="display_name"):
        validate_customer_identity(identity)


def test_validate_phone_contact_point_requires_canonical_phone() -> None:
    point = PhoneContactPoint(
        phone_contact_point_id="phone-1",
        customer_id="cust-1",
        normalized_phone="01700000099",
        display_phone="0170/0000099",
        status="active",
        created_at=_now(),
        updated_at=_now(),
    )
    with pytest.raises(ValueError, match="must already be canonical"):
        validate_phone_contact_point(point)


def test_validate_customer_identity_rejects_empty_customer_id() -> None:
    identity = CustomerIdentity(
        customer_id="  ",
        display_name="Name",
        company_name=None,
        status="active",
        created_at=_now(),
        updated_at=_now(),
    )
    with pytest.raises(ValueError, match="customer_id"):
        validate_customer_identity(identity)


def test_validate_customer_identity_rejects_naive_timestamp() -> None:
    naive = datetime(2026, 7, 19, 12, 0)
    identity = CustomerIdentity(
        customer_id="cust-1",
        display_name="Name",
        company_name=None,
        status="active",
        created_at=naive,
        updated_at=_now(),
    )
    with pytest.raises(ValueError, match="timezone-aware"):
        validate_customer_identity(identity)


def test_validate_phone_contact_point_rejects_invalid_validity_window() -> None:
    start = _now()
    end = start.replace(hour=start.hour - 1)
    point = PhoneContactPoint(
        phone_contact_point_id="phone-1",
        customer_id="cust-1",
        normalized_phone="+491700000099",
        display_phone=None,
        status="active",
        created_at=start,
        updated_at=start,
        valid_from=start,
        valid_to=end,
    )
    with pytest.raises(ValueError, match="valid_to must not be earlier"):
        validate_phone_contact_point(point)
