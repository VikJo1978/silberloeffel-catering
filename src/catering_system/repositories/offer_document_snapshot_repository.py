"""Persistence port for frozen customer offer document snapshots.

Append-only: exactly one snapshot per OfferVersion, never updated, never
deleted. The chosen variant is stored inside the snapshot, not in the key.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from catering_system.domain.offer_document_snapshot import OfferDocumentSnapshot


class OfferDocumentSnapshotRepository(ABC):
    @abstractmethod
    def get_by_id(
        self, offer_document_snapshot_id: str
    ) -> OfferDocumentSnapshot | None:
        raise NotImplementedError

    @abstractmethod
    def get_by_offer_version_id(
        self, offer_version_id: str
    ) -> OfferDocumentSnapshot | None:
        raise NotImplementedError

    @abstractmethod
    def insert(self, snapshot: OfferDocumentSnapshot) -> None:
        raise NotImplementedError
