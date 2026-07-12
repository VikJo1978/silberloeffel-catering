"""Inquiry persistence protocol."""

from __future__ import annotations

from typing import Protocol

from catering_system.domain.inquiry import Inquiry


class DuplicateExternalReferenceError(ValueError):
    """A source-scoped external idempotency key already exists."""


class InquiryRepository(Protocol):
    def save(self, inquiry: Inquiry) -> None: ...

    def get_by_id(self, inquiry_id: str) -> Inquiry | None: ...

    def list_all(self) -> list[Inquiry]: ...

    def update(self, inquiry: Inquiry) -> None: ...

    def find_by_source_and_external_ref(
        self, inquiry_source: str, intake_external_ref: str
    ) -> Inquiry | None: ...
