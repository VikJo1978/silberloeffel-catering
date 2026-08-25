"""In-memory explicit gastronomic preference repository."""

from __future__ import annotations

from catering_system.domain.customer_gastronomic_preference import (
    CustomerGastronomicPreference,
    validate_customer_gastronomic_preference,
)


class InMemoryCustomerGastronomicPreferenceRepository:
    def __init__(self) -> None:
        self._preferences: dict[str, CustomerGastronomicPreference] = {}

    def add(self, preference: CustomerGastronomicPreference) -> None:
        validate_customer_gastronomic_preference(preference)
        if preference.preference_id in self._preferences:
            raise KeyError(preference.preference_id)
        self._preferences[preference.preference_id] = preference

    def get_by_id(self, preference_id: str) -> CustomerGastronomicPreference | None:
        return self._preferences.get(preference_id)

    def list_by_customer(self, customer_id: str) -> list[CustomerGastronomicPreference]:
        rows = [
            preference
            for preference in self._preferences.values()
            if preference.customer_id == customer_id
        ]
        rows.sort(
            key=lambda preference: (preference.updated_at, preference.preference_id),
            reverse=True,
        )
        return rows

    def update(self, preference: CustomerGastronomicPreference) -> None:
        validate_customer_gastronomic_preference(preference)
        if preference.preference_id not in self._preferences:
            raise KeyError(preference.preference_id)
        self._preferences[preference.preference_id] = preference

    def delete(self, preference_id: str) -> None:
        if preference_id not in self._preferences:
            raise KeyError(preference_id)
        del self._preferences[preference_id]
