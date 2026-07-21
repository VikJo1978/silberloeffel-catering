"""Append-only internal contact notes for the Office Panel."""

from __future__ import annotations

import uuid

from catering_system.domain.contact_internal_note import (
    ContactInternalNote,
    utc_now,
    validate_contact_internal_note_category,
    validate_contact_internal_note_text,
)
from catering_system.repositories.contact_internal_note_repository import (
    ContactInternalNoteRepository,
)


class ContactInternalNoteService:
    def __init__(
        self,
        repository: ContactInternalNoteRepository,
        *,
        created_by: str,
    ) -> None:
        self._repository = repository
        self._created_by = created_by

    def list_for_contact(self, contact_key: str) -> list[ContactInternalNote]:
        return self._repository.list_for_contact(contact_key)

    def add_note(
        self,
        contact_key: str,
        *,
        category: str,
        note_text: str,
    ) -> ContactInternalNote:
        key = contact_key.strip()
        if not key:
            raise ValueError("contact_key is required")
        note = ContactInternalNote(
            note_id=str(uuid.uuid4()),
            contact_key=key,
            category=validate_contact_internal_note_category(category),
            note_text=validate_contact_internal_note_text(note_text),
            created_at=utc_now(),
            created_by=self._created_by,
        )
        self._repository.add(note)
        return note
