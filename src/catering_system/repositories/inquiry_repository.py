"""Inquiry persistence protocol."""

from __future__ import annotations

from typing import Protocol

from catering_system.domain.inquiry import Inquiry


class InquiryRepository(Protocol):
    def save(self, inquiry: Inquiry) -> None: ...

    def get_by_id(self, inquiry_id: str) -> Inquiry | None: ...

    def list_all(self) -> list[Inquiry]: ...

    def update(self, inquiry: Inquiry) -> None: ...
