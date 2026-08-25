"""Customer-scoped editing service for explicit gastronomic preferences.

Only deliberately recorded customer facts belong here. Order-history projections and
inferred recommendation hints are separate concerns and must not enter this service.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from catering_system.domain.customer_gastronomic_preference import (
    CustomerGastronomicPreference,
    PreferenceKind,
    PreferenceSource,
    validate_customer_gastronomic_preference,
)
from catering_system.repositories.customer_gastronomic_preference_repository import (
    CustomerGastronomicPreferenceRepository,
)
from catering_system.repositories.customer_identity_repository import (
    CustomerIdentityRepository,
)


class CustomerNotFoundError(LookupError):
    pass


class CustomerGastronomicPreferenceNotFoundError(LookupError):
    pass


class CustomerGastronomicPreferenceService:
    def __init__(
        self,
        customers: CustomerIdentityRepository,
        preferences: CustomerGastronomicPreferenceRepository,
        *,
        now: Callable[[], datetime] | None = None,
        new_id: Callable[[], str] | None = None,
    ) -> None:
        self._customers = customers
        self._preferences = preferences
        self._now = now or (lambda: datetime.now(UTC))
        self._new_id = new_id or (lambda: str(uuid.uuid4()))

    def list_for_customer(
        self, customer_id: str
    ) -> list[CustomerGastronomicPreference]:
        self._require_customer(customer_id)
        return self._preferences.list_by_customer(customer_id)

    def create(
        self,
        *,
        customer_id: str,
        kind: PreferenceKind,
        value: str,
        source: PreferenceSource,
    ) -> CustomerGastronomicPreference:
        self._require_customer(customer_id)
        now = self._now()
        preference = CustomerGastronomicPreference(
            preference_id=self._new_id(),
            customer_id=customer_id,
            kind=kind,
            value=value,
            source=source,
            created_at=now,
            updated_at=now,
        )
        validate_customer_gastronomic_preference(preference)
        self._preferences.add(preference)
        return preference

    def update(
        self,
        *,
        customer_id: str,
        preference_id: str,
        kind: PreferenceKind,
        value: str,
        source: PreferenceSource,
    ) -> CustomerGastronomicPreference:
        self._require_customer(customer_id)
        current = self._require_preference(customer_id, preference_id)
        updated = CustomerGastronomicPreference(
            preference_id=current.preference_id,
            customer_id=current.customer_id,
            kind=kind,
            value=value,
            source=source,
            created_at=current.created_at,
            updated_at=self._now(),
        )
        validate_customer_gastronomic_preference(updated)
        self._preferences.update(updated)
        return updated

    def delete(self, *, customer_id: str, preference_id: str) -> None:
        self._require_customer(customer_id)
        self._require_preference(customer_id, preference_id)
        self._preferences.delete(preference_id)

    def _require_customer(self, customer_id: str) -> None:
        if self._customers.get_by_id(customer_id) is None:
            raise CustomerNotFoundError(customer_id)

    def _require_preference(
        self, customer_id: str, preference_id: str
    ) -> CustomerGastronomicPreference:
        preference = self._preferences.get_by_id(preference_id)
        if preference is None or preference.customer_id != customer_id:
            raise CustomerGastronomicPreferenceNotFoundError(preference_id)
        return preference
