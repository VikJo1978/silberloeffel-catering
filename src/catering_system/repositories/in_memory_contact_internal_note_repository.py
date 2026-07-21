"""In-memory contact internal notes — tests and direct-mode fallback."""

from __future__ import annotations

from catering_system.domain.contact_internal_note import ContactInternalNote


class InMemoryContactInternalNoteRepository:
    def __init__(self) -> None:
        self._notes: list[ContactInternalNote] = []

    def add(self, note: ContactInternalNote) -> None:
        self._notes.append(note)

    def list_for_contact(self, contact_key: str) -> list[ContactInternalNote]:
        rows = [note for note in self._notes if note.contact_key == contact_key]
        rows.sort(key=lambda note: note.created_at, reverse=True)
        return rows
