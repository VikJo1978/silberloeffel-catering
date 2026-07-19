"""In-memory OrderConfirmationDocumentRepository for unit tests."""

from __future__ import annotations

from catering_system.domain.order_confirmation_document import (
    OrderConfirmationDocumentSnapshot,
)
from catering_system.repositories.order_confirmation_document_repository import (
    OrderConfirmationDocumentRepository,
)


class InMemoryOrderConfirmationDocumentRepository(OrderConfirmationDocumentRepository):
    def __init__(self) -> None:
        self._by_id: dict[str, OrderConfirmationDocumentSnapshot] = {}
        self._by_version: dict[str, OrderConfirmationDocumentSnapshot] = {}

    def get_by_id(
        self, document_snapshot_id: str
    ) -> OrderConfirmationDocumentSnapshot | None:
        return self._by_id.get(document_snapshot_id)

    def get_by_order_version_id(
        self, order_version_id: str
    ) -> OrderConfirmationDocumentSnapshot | None:
        return self._by_version.get(order_version_id)

    def get_latest_for_order(
        self, order_id: str
    ) -> OrderConfirmationDocumentSnapshot | None:
        matches = [
            snapshot
            for snapshot in self._by_id.values()
            if snapshot.order_id == order_id
        ]
        if not matches:
            return None
        return max(matches, key=lambda item: item.created_at)

    def insert(self, snapshot: OrderConfirmationDocumentSnapshot) -> None:
        if snapshot.document_snapshot_id in self._by_id:
            raise ValueError("document_snapshot_id already exists")
        if snapshot.order_version_id in self._by_version:
            raise ValueError("order_version_id already has a confirmation document")
        self._by_id[snapshot.document_snapshot_id] = snapshot
        self._by_version[snapshot.order_version_id] = snapshot
