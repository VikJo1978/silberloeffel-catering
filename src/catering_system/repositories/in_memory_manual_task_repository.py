"""In-memory manual task adapter for tests and direct-mode composition."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from catering_system.domain.manual_task import (
    ManualTask,
    ManualTaskSubjectType,
    validate_manual_task,
)


class InMemoryManualTaskRepository:
    def __init__(self) -> None:
        self._tasks: dict[str, ManualTask] = {}

    def get(self, task_id: str) -> ManualTask | None:
        return self._tasks.get(task_id)

    def save(self, task: ManualTask) -> None:
        validated = validate_manual_task(task)
        current = self._tasks.get(validated.task_id)
        if (
            current is not None
            and current.completed_at is not None
            and validated.completed_at != current.completed_at
        ):
            raise ValueError("completed manual task completion cannot be rewritten")
        self._tasks[validated.task_id] = validated

    def list_open(self) -> list[ManualTask]:
        rows = [task for task in self._tasks.values() if task.completed_at is None]
        rows.sort(key=_sort_key)
        return rows

    def list_for_subject(
        self, subject_type: ManualTaskSubjectType, subject_id: str
    ) -> list[ManualTask]:
        rows = [
            task
            for task in self._tasks.values()
            if task.subject_type == subject_type and task.subject_id == subject_id
        ]
        rows.sort(key=_sort_key)
        return rows

    def complete(self, task_id: str, completed_at: datetime) -> ManualTask:
        current = self._tasks.get(task_id)
        if current is None:
            raise KeyError(task_id)
        if current.completed_at is not None:
            return current
        completed = validate_manual_task(replace(current, completed_at=completed_at))
        self._tasks[task_id] = completed
        return completed


def _sort_key(task: ManualTask) -> tuple[datetime, datetime, str]:
    return (
        task.due_at or datetime.max.replace(tzinfo=task.created_at.tzinfo),
        task.created_at,
        task.task_id,
    )
