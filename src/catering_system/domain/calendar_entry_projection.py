"""Event calendar read projection — derived from existing Core facts only."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

CalendarEntryKind = Literal["event_confirmed", "event_planned", "event_tentative"]
CalendarEntityType = Literal["inquiry", "offer", "order"]

CALENDAR_ENTRY_KIND_LABELS: dict[CalendarEntryKind, str] = {
    "event_confirmed": "Bestätigt",
    "event_planned": "In Planung",
    "event_tentative": "Unverbindlich",
}


@dataclass(frozen=True)
class CalendarEntryProjection:
    """Office-facing calendar row; projection-only, not a Core entity."""

    entry_id: str
    entry_kind: CalendarEntryKind
    title: str
    event_date: date
    time_window_text: str
    location_text: str
    guest_count_estimate: int | None
    entity_type: CalendarEntityType
    entity_id: str
    action_label: str
    action_href: str
    source_inquiry_id: str


def calendar_title(
    intake_subject: str | None,
    location_text: str,
    inquiry_id: str,
) -> str:
    subject = (intake_subject or "").strip()
    if subject:
        return subject
    location = location_text.strip()
    if location:
        return location
    return inquiry_id[:8]


def calendar_sort_key(entry: CalendarEntryProjection) -> tuple[date, str, str]:
    return (entry.event_date, entry.time_window_text, entry.entry_id)
