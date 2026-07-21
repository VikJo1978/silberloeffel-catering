"""Internal contact notes — office-only Core facts, never customer-facing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

ContactInternalNoteCategory = Literal[
    "Allgemein",
    "Vorlieben",
    "Lieferung",
    "Zahlung",
    "Problem / Reklamation",
]

CONTACT_INTERNAL_NOTE_CATEGORIES: tuple[ContactInternalNoteCategory, ...] = (
    "Allgemein",
    "Vorlieben",
    "Lieferung",
    "Zahlung",
    "Problem / Reklamation",
)

CONTACT_INTERNAL_NOTE_CATEGORY_SET: frozenset[ContactInternalNoteCategory] = frozenset(
    CONTACT_INTERNAL_NOTE_CATEGORIES
)
MAX_CONTACT_INTERNAL_NOTE_LENGTH = 4000


@dataclass(frozen=True)
class ContactInternalNote:
    note_id: str
    contact_profile_id: str
    category: ContactInternalNoteCategory
    note_text: str
    created_at: datetime
    created_by: str


def validate_contact_internal_note_category(value: str) -> ContactInternalNoteCategory:
    if value not in CONTACT_INTERNAL_NOTE_CATEGORY_SET:
        raise ValueError(
            "category must be one of "
            f"{sorted(CONTACT_INTERNAL_NOTE_CATEGORY_SET)}, got {value!r}"
        )
    return value


def validate_contact_internal_note_text(value: str) -> str:
    text = value.strip()
    if not text:
        raise ValueError("note_text must not be empty")
    if len(text) > MAX_CONTACT_INTERNAL_NOTE_LENGTH:
        raise ValueError(
            f"note_text must be at most {MAX_CONTACT_INTERNAL_NOTE_LENGTH} characters"
        )
    return text


def utc_now() -> datetime:
    return datetime.now(UTC)
