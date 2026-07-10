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

    def list_all(self) -> list[Inquiry]:
        return sorted(self._by_id.values(), key=lambda i: (i.event_date, i.inquiry_id))

    def update(self, inquiry: Inquiry) -> None:
        if inquiry.inquiry_id not in self._by_id:
            raise KeyError(inquiry.inquiry_id)
        self._by_id[inquiry.inquiry_id] = inquiry

    def find_by_source_and_external_ref(
        self, inquiry_source: str, intake_external_ref: str
    ) -> Inquiry | None:
        for inquiry in self._by_id.values():
            if (
                inquiry.inquiry_source == inquiry_source
                and inquiry.intake_external_ref == intake_external_ref
            ):
                return inquiry
        return None
