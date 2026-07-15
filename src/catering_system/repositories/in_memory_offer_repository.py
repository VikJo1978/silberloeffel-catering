"""In-memory Offer repository — baseline for unit tests."""

from __future__ import annotations

from catering_system.domain.offer import AcceptanceEvidence, ConversionLink, Offer, SentEvidence


class InMemoryOfferRepository:
    def __init__(self) -> None:
        self._offers: dict[str, Offer] = {}

    def save(self, offer: Offer) -> None:
        if offer.offer_id in self._offers:
            raise KeyError(offer.offer_id)
        self._offers[offer.offer_id] = offer

    def get(self, offer_id: str) -> Offer | None:
        return self._offers.get(offer_id)

    def exists(self, offer_id: str) -> bool:
        return offer_id in self._offers

    def get_by_source_inquiry_id(self, inquiry_id: str) -> Offer | None:
        for offer in self._offers.values():
            if offer.source_inquiry_id == inquiry_id:
                return offer
        return None

    def append_sent_evidence(self, evidence: SentEvidence) -> Offer:
        offer = self.get(evidence.offer_id)
        if offer is None:
            raise KeyError(evidence.offer_id)
        updated = Offer(
            offer_id=offer.offer_id,
            source_inquiry_id=offer.source_inquiry_id,
            created_at=offer.created_at,
            versions=offer.versions,
            sent_evidence=(*offer.sent_evidence, evidence),
            acceptance_evidence=offer.acceptance_evidence,
            rejection_evidence=offer.rejection_evidence,
            withdrawal_evidence=offer.withdrawal_evidence,
            conversion_link=offer.conversion_link,
        )
        self._offers[offer.offer_id] = updated
        return updated

    def append_acceptance_evidence(self, evidence: AcceptanceEvidence) -> Offer:
        offer = self.get(evidence.offer_id)
        if offer is None:
            raise KeyError(evidence.offer_id)
        if offer.acceptance_evidence is not None:
            raise ValueError(
                f"acceptance already exists for offer_id={evidence.offer_id!r}"
            )
        updated = Offer(
            offer_id=offer.offer_id,
            source_inquiry_id=offer.source_inquiry_id,
            created_at=offer.created_at,
            versions=offer.versions,
            sent_evidence=offer.sent_evidence,
            acceptance_evidence=evidence,
            rejection_evidence=offer.rejection_evidence,
            withdrawal_evidence=offer.withdrawal_evidence,
            conversion_link=offer.conversion_link,
        )
        self._offers[offer.offer_id] = updated
        return updated

    def append_conversion_link(self, link: ConversionLink) -> Offer:
        offer = self.get(link.offer_id)
        if offer is None:
            raise KeyError(link.offer_id)
        if offer.conversion_link is not None:
            raise ValueError(
                f"conversion link already exists for offer_id={link.offer_id!r}"
            )
        updated = Offer(
            offer_id=offer.offer_id,
            source_inquiry_id=offer.source_inquiry_id,
            created_at=offer.created_at,
            versions=offer.versions,
            sent_evidence=offer.sent_evidence,
            acceptance_evidence=offer.acceptance_evidence,
            rejection_evidence=offer.rejection_evidence,
            withdrawal_evidence=offer.withdrawal_evidence,
            conversion_link=link,
        )
        self._offers[offer.offer_id] = updated
        return updated
