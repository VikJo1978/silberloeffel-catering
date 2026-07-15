"""Offer persistence protocol — commercial aggregate storage only."""

from __future__ import annotations

from typing import Protocol

from catering_system.domain.offer import AcceptanceEvidence, Offer, SentEvidence


class OfferRepository(Protocol):
    def save(self, offer: Offer) -> None:
        """Persist a complete Offer aggregate as one atomic write."""

    def get(self, offer_id: str) -> Offer | None:
        """Load a complete Offer aggregate or return None."""

    def exists(self, offer_id: str) -> bool:
        """Return whether an Offer aggregate is already stored."""

    def get_by_source_inquiry_id(self, inquiry_id: str) -> Offer | None:
        """Load the Offer linked to an Inquiry, if any."""

    def append_sent_evidence(self, evidence: SentEvidence) -> Offer:
        """Append one SentEvidence row and return the updated Offer aggregate."""

    def append_acceptance_evidence(self, evidence: AcceptanceEvidence) -> Offer:
        """Append one AcceptanceEvidence row and return the updated Offer aggregate."""
