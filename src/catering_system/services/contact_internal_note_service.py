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
from catering_system.services.contact_profile_service import ContactProfileService


class ContactInternalNoteService:
    def __init__(
        self,
        repository: ContactInternalNoteRepository,
        profile_service: ContactProfileService,
        *,
        created_by: str,
    ) -> None:
        self._repository = repository
        self._profiles = profile_service
        self._created_by = created_by

    def list_for_profile(self, contact_profile_id: str) -> list[ContactInternalNote]:
        profile_ids = self._profiles.profile_ids_for_notes(contact_profile_id)
        return self._repository.list_for_profiles(profile_ids)

    def add_note(
        self,
        contact_profile_id: str,
        *,
        category: str,
        note_text: str,
    ) -> ContactInternalNote:
        root = self._profiles.resolve_root_profile_id(contact_profile_id.strip())
        if not root:
            raise ValueError("contact_profile_id is required")
        note = ContactInternalNote(
            note_id=str(uuid.uuid4()),
            contact_profile_id=root,
            category=validate_contact_internal_note_category(category),
            note_text=validate_contact_internal_note_text(note_text),
            created_at=utc_now(),
            created_by=self._created_by,
        )
        self._repository.add(note)
        return note
