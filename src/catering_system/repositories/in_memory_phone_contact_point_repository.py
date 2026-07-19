"""In-memory PhoneContactPoint repository."""

from __future__ import annotations

from catering_system.domain.customer_identity import (
    ACTIVE_CUSTOMER_IDENTITY_STATUS,
    ACTIVE_PHONE_CONTACT_POINT_STATUS,
    PhoneContactPoint,
    validate_phone_contact_point,
)
from catering_system.domain.phone_normalization import normalize_phone_for_contact_point
from catering_system.repositories.customer_identity_repository import (
    CustomerIdentityRepository,
)
from catering_system.repositories.in_memory_customer_identity_repository import (
    InMemoryCustomerIdentityRepository,
)


class InMemoryPhoneContactPointRepository:
    def __init__(
        self, customer_identities: CustomerIdentityRepository | None = None
    ) -> None:
        self._customers = customer_identities or InMemoryCustomerIdentityRepository()
        self._by_id: dict[str, PhoneContactPoint] = {}

    @property
    def customer_identities(self) -> CustomerIdentityRepository:
        return self._customers

    def add(self, point: PhoneContactPoint) -> None:
        validate_phone_contact_point(point)
        if self._customers.get_by_id(point.customer_id) is None:
            raise KeyError(point.customer_id)
        if point.phone_contact_point_id in self._by_id:
            raise KeyError(point.phone_contact_point_id)
        self._by_id[point.phone_contact_point_id] = point

    def get_by_id(self, phone_contact_point_id: str) -> PhoneContactPoint | None:
        return self._by_id.get(phone_contact_point_id)

    def list_by_customer_id(self, customer_id: str) -> list[PhoneContactPoint]:
        return sorted(
            (
                point
                for point in self._by_id.values()
                if point.customer_id == customer_id
            ),
            key=lambda point: (point.created_at, point.phone_contact_point_id),
        )

    def find_active_by_normalized_phone(
        self, normalized_phone: str
    ) -> list[PhoneContactPoint]:
        canonical = normalize_phone_for_contact_point(normalized_phone)
        matches = [
            point
            for point in self._by_id.values()
            if point.normalized_phone == canonical
            and point.status == ACTIVE_PHONE_CONTACT_POINT_STATUS
        ]
        active: list[PhoneContactPoint] = []
        for point in sorted(
            matches, key=lambda p: (p.created_at, p.phone_contact_point_id)
        ):
            customer = self._customers.get_by_id(point.customer_id)
            if customer is None or customer.status != ACTIVE_CUSTOMER_IDENTITY_STATUS:
                continue
            active.append(point)
        return active
