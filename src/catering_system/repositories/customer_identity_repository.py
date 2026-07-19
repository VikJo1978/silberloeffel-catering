"""CustomerIdentity persistence protocol."""

from __future__ import annotations

from typing import Protocol

from catering_system.domain.customer_identity import CustomerIdentity


class CustomerIdentityRepository(Protocol):
    def add(self, identity: CustomerIdentity) -> None: ...

    def get_by_id(self, customer_id: str) -> CustomerIdentity | None: ...

    def update(self, identity: CustomerIdentity) -> None: ...
