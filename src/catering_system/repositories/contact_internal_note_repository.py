"""Repository contract for append-only contact internal notes."""

from __future__ import annotations

from typing import Protocol

from catering_system.domain.contact_internal_note import ContactInternalNote


class ContactInternalNoteRepository(Protocol):
    def add(self, note: ContactInternalNote) -> None: ...

    def list_for_contact(self, contact_key: str) -> list[ContactInternalNote]: ...
