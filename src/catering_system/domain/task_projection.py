"""System task read projection — derived from existing Core facts only."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

TaskCategory = Literal[
    "verify",
    "convert",
    "convert_accepted",
    "order_print",
    "order_effective",
    "payment",
]
TaskEntityType = Literal["inquiry", "offer", "order"]
TaskUrgency = Literal["overdue", "normal"]


@dataclass(frozen=True)
class TaskProjection:
    """Office-facing system task row; projection-only, not a Core entity."""

    task_id: str
    category: TaskCategory
    title: str
    subtitle: str
    entity_type: TaskEntityType
    entity_id: str
    action_label: str
    action_href: str
    due_at: date | None
    urgency: TaskUrgency
    opened_at: datetime


def inquiry_subtitle(
    intake_subject: str | None, location_text: str, inquiry_id: str
) -> str:
    subject = (intake_subject or "").strip()
    if subject:
        return subject
    location = location_text.strip()
    if location:
        return location
    return inquiry_id[:8]


def task_sort_key(
    task: TaskProjection, *, event_date: date
) -> tuple[int, date, date, str]:
    tier = _sort_tier(task)
    due = task.due_at or date.max
    return (tier, due, event_date, task.task_id)


def _sort_tier(task: TaskProjection) -> int:
    if task.category == "payment" and task.urgency == "overdue":
        return 0
    if task.category == "verify":
        return 1
    if task.category == "order_print":
        return 2
    if task.category == "order_effective":
        return 3
    if task.category == "convert_accepted":
        return 4
    if task.category == "payment":
        return 5
    if task.category == "convert":
        return 6
    raise AssertionError(f"unexpected task category: {task.category!r}")
