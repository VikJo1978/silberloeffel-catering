"""Persistence protocol for explicit customer gastronomic preferences."""

from __future__ import annotations

from typing import Protocol

from catering_system.domain.customer_gastronomic_preference import (
    CustomerGastronomicPreference,
)


class CustomerGastronomicPreferenceRepository(Protocol):
    def add(self, preference: CustomerGastronomicPreference) -> None: ...

    def get_by_id(self, preference_id: str) -> CustomerGastronomicPreference | None: ...

    def list_by_customer(
        self, customer_id: str
    ) -> list[CustomerGastronomicPreference]: ...

    def update(self, preference: CustomerGastronomicPreference) -> None: ...

    def delete(self, preference_id: str) -> None: ...
