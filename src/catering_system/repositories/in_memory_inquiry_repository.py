"""In-memory inquiry repository."""

from __future__ import annotations

from catering_system.domain.inquiry import Inquiry


class InMemoryInquiryRepository:
    def __init__(self) -> None:
        self._by_id: dict[str, Inquiry] = {}

    def save(self, inquiry: Inquiry) -> None:
        self._by_id[inquiry.inquiry_id] = inquiry

    def get_by_id(self, inquiry_id: str) -> Inquiry | None:
        return self._by_id.get(inquiry_id)

    def update(self, inquiry: Inquiry) -> None:
        if inquiry.inquiry_id not in self._by_id:
            raise KeyError(inquiry.inquiry_id)
        self._by_id[inquiry.inquiry_id] = inquiry
