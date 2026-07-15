"""In-memory Offer repository — baseline for unit tests."""

from __future__ import annotations

from catering_system.domain.offer import Offer


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
