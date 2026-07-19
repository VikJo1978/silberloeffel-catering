"""In-memory PhoneContactPoint repository tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from catering_system.domain.customer_identity import CustomerIdentity, PhoneContactPoint
from catering_system.repositories.in_memory_customer_identity_repository import (
    InMemoryCustomerIdentityRepository,
)
from catering_system.repositories.in_memory_phone_contact_point_repository import (
    InMemoryPhoneContactPointRepository,
)

PHONE_A = "+491700000099"
PHONE_B = "+491700000098"


def _now() -> datetime:
    return datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)


def _customer(customer_id: str, *, status: str = "active") -> CustomerIdentity:
    return CustomerIdentity(
        customer_id=customer_id,
        display_name=f"Customer {customer_id[:4]}",
        company_name=None,
        status=status,  # type: ignore[arg-type]
        created_at=_now(),
        updated_at=_now(),
    )


def _phone(
    phone_id: str,
    customer_id: str,
    *,
    normalized_phone: str = PHONE_A,
    display_phone: str | None = "0170/0000099",
    status: str = "active",
) -> PhoneContactPoint:
    return PhoneContactPoint(
        phone_contact_point_id=phone_id,
        customer_id=customer_id,
        normalized_phone=normalized_phone,
        display_phone=display_phone,
        status=status,  # type: ignore[arg-type]
        created_at=_now(),
        updated_at=_now(),
    )


def test_create_get_and_list_by_customer() -> None:
    customers = InMemoryCustomerIdentityRepository()
    customer = _customer("cust-1")
    customers.add(customer)
    repo = InMemoryPhoneContactPointRepository(customers)
    point = _phone("phone-1", customer.customer_id)
    repo.add(point)
    assert repo.get_by_id("phone-1") == point
    assert repo.list_by_customer_id(customer.customer_id) == [point]


def test_exact_lookup_returns_single_match() -> None:
    customers = InMemoryCustomerIdentityRepository()
    customer = _customer("cust-1")
    customers.add(customer)
    repo = InMemoryPhoneContactPointRepository(customers)
    repo.add(_phone("phone-1", customer.customer_id))
    matches = repo.find_active_by_normalized_phone(PHONE_A)
    assert len(matches) == 1
    assert matches[0].phone_contact_point_id == "phone-1"


def test_inactive_phone_excluded() -> None:
    customers = InMemoryCustomerIdentityRepository()
    customer = _customer("cust-1")
    customers.add(customer)
    repo = InMemoryPhoneContactPointRepository(customers)
    repo.add(_phone("phone-1", customer.customer_id, status="inactive"))
    assert repo.find_active_by_normalized_phone(PHONE_A) == []


def test_merged_customer_excluded_from_active_candidates() -> None:
    customers = InMemoryCustomerIdentityRepository()
    customer = _customer("cust-1", status="merged")
    customers.add(customer)
    repo = InMemoryPhoneContactPointRepository(customers)
    repo.add(_phone("phone-1", customer.customer_id))
    assert repo.find_active_by_normalized_phone(PHONE_A) == []


def test_multiple_identities_with_same_number_returned() -> None:
    customers = InMemoryCustomerIdentityRepository()
    first = _customer("cust-1")
    second = _customer("cust-2")
    customers.add(first)
    customers.add(second)
    repo = InMemoryPhoneContactPointRepository(customers)
    repo.add(_phone("phone-1", first.customer_id))
    repo.add(_phone("phone-2", second.customer_id, display_phone="0170 0000099"))
    matches = repo.find_active_by_normalized_phone(PHONE_A)
    assert {point.phone_contact_point_id for point in matches} == {"phone-1", "phone-2"}


def test_display_phone_does_not_affect_matching() -> None:
    customers = InMemoryCustomerIdentityRepository()
    customer = _customer("cust-1")
    customers.add(customer)
    repo = InMemoryPhoneContactPointRepository(customers)
    repo.add(_phone("phone-1", customer.customer_id, display_phone="different"))
    assert repo.find_active_by_normalized_phone(PHONE_A)[0].display_phone == "different"


def test_duplicate_phone_point_id_rejected() -> None:
    customers = InMemoryCustomerIdentityRepository()
    customer = _customer("cust-1")
    customers.add(customer)
    repo = InMemoryPhoneContactPointRepository(customers)
    repo.add(_phone("phone-1", customer.customer_id))
    with pytest.raises(KeyError):
        repo.add(replace(_phone("phone-1", customer.customer_id), display_phone="x"))


def test_similar_number_without_shared_normalized_phone_not_matched() -> None:
    customers = InMemoryCustomerIdentityRepository()
    customer = _customer("cust-1")
    customers.add(customer)
    repo = InMemoryPhoneContactPointRepository(customers)
    repo.add(_phone("phone-1", customer.customer_id, normalized_phone=PHONE_B))
    assert repo.find_active_by_normalized_phone(PHONE_A) == []


def test_invalid_domain_values_rejected() -> None:
    customers = InMemoryCustomerIdentityRepository()
    customer = _customer("cust-1")
    customers.add(customer)
    repo = InMemoryPhoneContactPointRepository(customers)
    with pytest.raises(ValueError):
        repo.add(_phone("phone-1", customer.customer_id, normalized_phone="anonymous"))


def test_missing_customer_rejected_on_add() -> None:
    repo = InMemoryPhoneContactPointRepository()
    with pytest.raises(KeyError):
        repo.add(_phone("phone-1", "missing-customer"))
