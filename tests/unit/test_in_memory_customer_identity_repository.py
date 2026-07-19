"""In-memory CustomerIdentity repository tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from catering_system.domain.customer_identity import CustomerIdentity
from catering_system.repositories.in_memory_customer_identity_repository import (
    InMemoryCustomerIdentityRepository,
)


def _now() -> datetime:
    return datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)


def _sample_identity(**overrides: object) -> CustomerIdentity:
    base = CustomerIdentity(
        customer_id="11111111-1111-1111-1111-111111111111",
        display_name="Muster GmbH",
        company_name="Muster GmbH",
        status="active",
        created_at=_now(),
        updated_at=_now(),
    )
    return replace(base, **overrides)


def test_create_and_get_customer() -> None:
    repo = InMemoryCustomerIdentityRepository()
    identity = _sample_identity()
    repo.add(identity)
    loaded = repo.get_by_id(identity.customer_id)
    assert loaded == identity


def test_duplicate_customer_id_rejected() -> None:
    repo = InMemoryCustomerIdentityRepository()
    identity = _sample_identity()
    repo.add(identity)
    with pytest.raises(KeyError):
        repo.add(replace(identity, display_name="Other Name"))


def test_update_existing_customer() -> None:
    repo = InMemoryCustomerIdentityRepository()
    identity = _sample_identity()
    repo.add(identity)
    updated = replace(identity, display_name="Updated Name", updated_at=_now())
    repo.update(updated)
    assert repo.get_by_id(identity.customer_id) == updated


def test_update_missing_customer_raises() -> None:
    repo = InMemoryCustomerIdentityRepository()
    with pytest.raises(KeyError):
        repo.update(_sample_identity())


def test_invalid_status_rejected_on_add() -> None:
    repo = InMemoryCustomerIdentityRepository()
    with pytest.raises(ValueError, match="customer identity status"):
        repo.add(replace(_sample_identity(), status="not-a-status"))  # type: ignore[arg-type]
