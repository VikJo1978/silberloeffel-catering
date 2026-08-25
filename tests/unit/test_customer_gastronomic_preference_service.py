from datetime import UTC, datetime, timedelta

import pytest

from catering_system.domain.customer_identity import CustomerIdentity
from catering_system.repositories.in_memory_customer_gastronomic_preference_repository import (
    InMemoryCustomerGastronomicPreferenceRepository,
)
from catering_system.repositories.in_memory_customer_identity_repository import (
    InMemoryCustomerIdentityRepository,
)
from catering_system.services.customer_gastronomic_preference_service import (
    CustomerGastronomicPreferenceNotFoundError,
    CustomerGastronomicPreferenceService,
    CustomerNotFoundError,
)


NOW = datetime(2026, 8, 25, 18, 0, tzinfo=UTC)


def _customer(customer_id: str = "customer-1") -> CustomerIdentity:
    return CustomerIdentity(
        customer_id=customer_id,
        display_name="Testkunde",
        company_name=None,
        status="active",
        created_at=NOW - timedelta(days=1),
        updated_at=NOW - timedelta(days=1),
    )


def _service():
    customers = InMemoryCustomerIdentityRepository()
    preferences = InMemoryCustomerGastronomicPreferenceRepository()
    service = CustomerGastronomicPreferenceService(
        customers,
        preferences,
        now=lambda: NOW,
        new_id=lambda: "pref-1",
    )
    return service, customers, preferences


def test_create_requires_existing_customer_and_persists_only_explicit_fact() -> None:
    service, customers, preferences = _service()
    with pytest.raises(CustomerNotFoundError):
        service.create(
            customer_id="missing",
            kind="favorite_dish",
            value="Mini-Frikadellen",
            source="customer_stated",
        )

    customers.add(_customer())
    created = service.create(
        customer_id="customer-1",
        kind="favorite_dish",
        value="Mini-Frikadellen",
        source="customer_stated",
    )

    assert created.preference_id == "pref-1"
    assert created.customer_id == "customer-1"
    assert created.created_at == NOW
    assert created.updated_at == NOW
    assert preferences.get_by_id("pref-1") == created


def test_list_requires_existing_customer() -> None:
    service, customers, _ = _service()
    with pytest.raises(CustomerNotFoundError):
        service.list_for_customer("missing")

    customers.add(_customer())
    assert service.list_for_customer("customer-1") == []


def test_update_preserves_customer_and_created_at() -> None:
    service, customers, preferences = _service()
    customers.add(_customer())
    created = service.create(
        customer_id="customer-1",
        kind="favorite_dish",
        value="Mini-Frikadellen",
        source="customer_stated",
    )

    later = NOW + timedelta(minutes=5)
    service._now = lambda: later
    updated = service.update(
        customer_id="customer-1",
        preference_id="pref-1",
        kind="disliked_dish",
        value="Leber",
        source="office_recorded",
    )

    assert updated.customer_id == created.customer_id
    assert updated.created_at == created.created_at
    assert updated.updated_at == later
    assert updated.kind == "disliked_dish"
    assert updated.source == "office_recorded"
    assert preferences.get_by_id("pref-1") == updated


def test_customer_scoping_hides_other_customers_preferences() -> None:
    service, customers, preferences = _service()
    customers.add(_customer("customer-1"))
    customers.add(_customer("customer-2"))
    created = service.create(
        customer_id="customer-1",
        kind="service_style",
        value="Buffet",
        source="office_recorded",
    )

    with pytest.raises(CustomerGastronomicPreferenceNotFoundError):
        service.update(
            customer_id="customer-2",
            preference_id=created.preference_id,
            kind="service_style",
            value="Fingerfood",
            source="office_recorded",
        )
    with pytest.raises(CustomerGastronomicPreferenceNotFoundError):
        service.delete(
            customer_id="customer-2",
            preference_id=created.preference_id,
        )

    assert preferences.get_by_id(created.preference_id) == created


def test_delete_removes_preference_but_not_customer_identity() -> None:
    service, customers, preferences = _service()
    customer = _customer()
    customers.add(customer)
    created = service.create(
        customer_id=customer.customer_id,
        kind="spice_level",
        value="mild",
        source="customer_stated",
    )

    service.delete(customer_id=customer.customer_id, preference_id=created.preference_id)

    assert preferences.get_by_id(created.preference_id) is None
    assert customers.get_by_id(customer.customer_id) == customer


def test_inferred_source_is_rejected_by_domain_boundary() -> None:
    service, customers, _ = _service()
    customers.add(_customer())
    with pytest.raises(ValueError, match="source must be explicit"):
        service.create(
            customer_id="customer-1",
            kind="favorite_dish",
            value="Mini-Frikadellen",
            source="inferred",  # type: ignore[arg-type]
        )
