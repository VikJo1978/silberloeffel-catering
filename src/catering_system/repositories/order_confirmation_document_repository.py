"""Persistence port for frozen Order confirmation document snapshots."""

from __future__ import annotations

from abc import ABC, abstractmethod

from catering_system.domain.order_confirmation_document import (
    OrderConfirmationDocumentSnapshot,
)


class OrderConfirmationDocumentRepository(ABC):
    @abstractmethod
    def get_by_id(
        self, document_snapshot_id: str
    ) -> OrderConfirmationDocumentSnapshot | None:
        raise NotImplementedError

    @abstractmethod
    def get_by_order_version_id(
        self, order_version_id: str
    ) -> OrderConfirmationDocumentSnapshot | None:
        raise NotImplementedError

    @abstractmethod
    def get_latest_for_order(
        self, order_id: str
    ) -> OrderConfirmationDocumentSnapshot | None:
        raise NotImplementedError

    @abstractmethod
    def insert(self, snapshot: OrderConfirmationDocumentSnapshot) -> None:
        raise NotImplementedError
