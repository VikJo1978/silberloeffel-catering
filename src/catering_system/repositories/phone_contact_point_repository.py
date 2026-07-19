"""PhoneContactPoint persistence protocol."""

from __future__ import annotations

from typing import Protocol

from catering_system.domain.customer_identity import PhoneContactPoint


class PhoneContactPointRepository(Protocol):
    def add(self, point: PhoneContactPoint) -> None: ...

    def get_by_id(self, phone_contact_point_id: str) -> PhoneContactPoint | None: ...

    def list_by_customer_id(self, customer_id: str) -> list[PhoneContactPoint]: ...

    def find_active_by_normalized_phone(
        self, normalized_phone: str
    ) -> list[PhoneContactPoint]: ...
