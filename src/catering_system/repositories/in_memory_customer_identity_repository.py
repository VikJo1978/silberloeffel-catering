"""In-memory CustomerIdentity repository."""

from __future__ import annotations

from catering_system.domain.customer_identity import (
    CustomerIdentity,
    validate_customer_identity,
)


class InMemoryCustomerIdentityRepository:
    def __init__(self) -> None:
        self._by_id: dict[str, CustomerIdentity] = {}

    def add(self, identity: CustomerIdentity) -> None:
        validate_customer_identity(identity)
        if identity.customer_id in self._by_id:
            raise KeyError(identity.customer_id)
        self._by_id[identity.customer_id] = identity

    def get_by_id(self, customer_id: str) -> CustomerIdentity | None:
        return self._by_id.get(customer_id)

    def update(self, identity: CustomerIdentity) -> None:
        validate_customer_identity(identity)
        if identity.customer_id not in self._by_id:
            raise KeyError(identity.customer_id)
        self._by_id[identity.customer_id] = identity
