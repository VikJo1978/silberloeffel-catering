"""In-memory inquiry repository."""

from __future__ import annotations

from catering_system.domain.inquiry import Inquiry
from catering_system.repositories.inquiry_repository import (
    DuplicateExternalReferenceError,
)


class InMemoryInquiryRepository:
    def __init__(self) -> None:
        self._by_id: dict[str, Inquiry] = {}

    def save(self, inquiry: Inquiry) -> None:
        if inquiry.inquiry_id in self._by_id:
            raise KeyError(inquiry.inquiry_id)
        self._ensure_external_ref_available(inquiry)
        self._by_id[inquiry.inquiry_id] = inquiry

    def get_by_id(self, inquiry_id: str) -> Inquiry | None:
        return self._by_id.get(inquiry_id)

    def list_all(self) -> list[Inquiry]:
        return sorted(self._by_id.values(), key=lambda i: (i.event_date, i.inquiry_id))

    def update(self, inquiry: Inquiry) -> None:
        if inquiry.inquiry_id not in self._by_id:
            raise KeyError(inquiry.inquiry_id)
        self._ensure_external_ref_available(inquiry)
        self._by_id[inquiry.inquiry_id] = inquiry

    def _ensure_external_ref_available(self, inquiry: Inquiry) -> None:
        if inquiry.inquiry_source != "website_form" or not inquiry.intake_external_ref:
            return
        for existing in self._by_id.values():
            if (
                existing.inquiry_id != inquiry.inquiry_id
                and existing.inquiry_source == "website_form"
                and existing.intake_external_ref == inquiry.intake_external_ref
            ):
                raise DuplicateExternalReferenceError(
                    "website_form submission_id already exists"
                )

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
