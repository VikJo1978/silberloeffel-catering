"""In-memory offer document snapshot repository — baseline for unit tests.

Mirrors the SQLite adapter's guarantees: one snapshot per OfferVersion,
insert-once, and the same runtime hash verification on every read so tests
exercise the real read contract rather than a laxer one.
"""

from __future__ import annotations

from catering_system.domain.offer_document_snapshot import OfferDocumentSnapshot
from catering_system.repositories.offer_document_snapshot_repository import (
    OfferDocumentSnapshotRepository,
)
from catering_system.services.offer_document_snapshot_serialization import (
    snapshot_from_verified_row,
    snapshot_to_canonical_json,
)


class InMemoryOfferDocumentSnapshotRepository(OfferDocumentSnapshotRepository):
    def __init__(self) -> None:
        # Stored as canonical JSON + row hash so the verification path is the
        # same one SQLite uses.
        self._rows: dict[str, tuple[str, str]] = {}
        self._by_offer_version_id: dict[str, str] = {}

    def get_by_id(
        self, offer_document_snapshot_id: str
    ) -> OfferDocumentSnapshot | None:
        row = self._rows.get(offer_document_snapshot_id)
        if row is None:
            return None
        canonical, row_hash = row
        return snapshot_from_verified_row(canonical, row_hash)

    def get_by_offer_version_id(
        self, offer_version_id: str
    ) -> OfferDocumentSnapshot | None:
        snapshot_id = self._by_offer_version_id.get(offer_version_id)
        if snapshot_id is None:
            return None
        return self.get_by_id(snapshot_id)

    def insert(self, snapshot: OfferDocumentSnapshot) -> None:
        if snapshot.offer_document_snapshot_id in self._rows:
            raise KeyError(snapshot.offer_document_snapshot_id)
        if snapshot.offer_version_id in self._by_offer_version_id:
            raise ValueError(
                "offer document snapshot already exists for offer_version_id="
                f"{snapshot.offer_version_id!r}"
            )
        self._rows[snapshot.offer_document_snapshot_id] = (
            snapshot_to_canonical_json(snapshot),
            snapshot.document_hash,
        )
        self._by_offer_version_id[snapshot.offer_version_id] = (
            snapshot.offer_document_snapshot_id
        )
