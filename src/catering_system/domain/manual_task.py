"""Manual office tasks — persisted employee-owned task facts."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Literal, cast

ManualTaskSubjectType = Literal["NONE", "ORDER", "INQUIRY", "CONTACT"]
MANUAL_TASK_SUBJECT_TYPES: tuple[ManualTaskSubjectType, ...] = (
    "NONE",
    "ORDER",
    "INQUIRY",
    "CONTACT",
)
MANUAL_TASK_SUBJECT_TYPE_SET: frozenset[str] = frozenset(MANUAL_TASK_SUBJECT_TYPES)

ManualTaskStatus = Literal["OPEN", "DONE"]

MAX_MANUAL_TASK_TITLE_LENGTH = 200
MAX_MANUAL_TASK_DESCRIPTION_LENGTH = 4000


@dataclass(frozen=True)
class ManualTask:
    task_id: str
    title: str
    description: str
    due_at: datetime | None
    created_at: datetime
    completed_at: datetime | None
    created_by_employee_id: str
    assigned_to_employee_id: str | None
    subject_type: ManualTaskSubjectType
    subject_id: str | None

    @property
    def status(self) -> ManualTaskStatus:
        return "DONE" if self.completed_at is not None else "OPEN"


def validate_manual_task_subject_type(value: str) -> ManualTaskSubjectType:
    if value not in MANUAL_TASK_SUBJECT_TYPE_SET:
        raise ValueError(
            "subject_type must be one of "
            f"{sorted(MANUAL_TASK_SUBJECT_TYPE_SET)}, got {value!r}"
        )
    return cast(ManualTaskSubjectType, value)


def normalize_manual_task_title(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("title must be a string")
    title = value.strip()
    if not title:
        raise ValueError("title must not be empty")
    if len(title) > MAX_MANUAL_TASK_TITLE_LENGTH:
        raise ValueError(
            f"title must be at most {MAX_MANUAL_TASK_TITLE_LENGTH} characters"
        )
    return title


def normalize_manual_task_description(value: object | None) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise TypeError("description must be a string or null")
    description = value.strip()
    if len(description) > MAX_MANUAL_TASK_DESCRIPTION_LENGTH:
        raise ValueError(
            "description must be at most "
            f"{MAX_MANUAL_TASK_DESCRIPTION_LENGTH} characters"
        )
    return description


def validate_manual_task(task: ManualTask) -> ManualTask:
    task_id = _require_uuid4(task.task_id, "task_id")
    title = normalize_manual_task_title(task.title)
    description = normalize_manual_task_description(task.description)
    created_by = _require_non_empty_string(
        task.created_by_employee_id, "created_by_employee_id"
    )
    assigned_to = (
        _require_non_empty_string(
            task.assigned_to_employee_id, "assigned_to_employee_id"
        )
        if task.assigned_to_employee_id is not None
        else None
    )
    subject_type = validate_manual_task_subject_type(task.subject_type)
    subject_id = _validate_subject_id(subject_type, task.subject_id)
    _require_utc_datetime(task.created_at, "created_at")
    if task.due_at is not None:
        _require_utc_datetime(task.due_at, "due_at")
    if task.completed_at is not None:
        _require_utc_datetime(task.completed_at, "completed_at")
        if task.completed_at < task.created_at:
            raise ValueError("completed_at must not be earlier than created_at")
    return replace(
        task,
        task_id=task_id,
        title=title,
        description=description,
        created_by_employee_id=created_by,
        assigned_to_employee_id=assigned_to,
        subject_type=subject_type,
        subject_id=subject_id,
    )


def _validate_subject_id(
    subject_type: ManualTaskSubjectType, subject_id: str | None
) -> str | None:
    if subject_type == "NONE":
        if subject_id is not None:
            raise ValueError("subject_id must be null when subject_type is NONE")
        return None
    if subject_id is None:
        raise ValueError("subject_id is required when subject_type is not NONE")
    return _require_uuid4(subject_id, "subject_id")


def _require_non_empty_string(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    text = value.strip()
    if not text:
        raise ValueError(f"{field} must not be empty")
    return text


def _require_uuid4(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a UUID string")
    try:
        parsed = uuid.UUID(value)
    except ValueError as exc:
        raise ValueError(f"{field} must be a UUID string") from exc
    if parsed.version != 4:
        raise ValueError(f"{field} must be a UUID4 string")
    normalized = str(parsed)
    if value != normalized:
        raise ValueError(f"{field} must be a canonical UUID4 string")
    return normalized


def _require_utc_datetime(value: datetime, field: str) -> None:
    if not isinstance(value, datetime) or value.utcoffset() != timedelta(0):
        raise ValueError(f"{field} must be a timezone-aware UTC timestamp")
