"""Application service for manual office tasks."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime

from catering_system.domain.manual_task import (
    ManualTask,
    ManualTaskSubjectType,
    normalize_manual_task_description,
    normalize_manual_task_title,
    validate_manual_task,
    validate_manual_task_priority,
    validate_manual_task_subject_type,
)
from catering_system.repositories.manual_task_repository import ManualTaskRepository

EmployeeExists = Callable[[str], bool]
SubjectExists = Callable[[ManualTaskSubjectType, str], bool]
IdFactory = Callable[[], str]
Clock = Callable[[], datetime]


class ManualTaskService:
    def __init__(
        self,
        repository: ManualTaskRepository,
        *,
        employee_exists: EmployeeExists,
        subject_exists: SubjectExists | None = None,
        id_factory: IdFactory | None = None,
        now: Clock | None = None,
    ) -> None:
        self._repository = repository
        self._employee_exists = employee_exists
        self._subject_exists = subject_exists or _subject_exists_default
        self._id_factory = id_factory or (lambda: str(uuid.uuid4()))
        self._now = now or (lambda: datetime.now(UTC))

    def create_task(
        self,
        *,
        title: str,
        description: str | None = None,
        due_at: datetime | None = None,
        created_by_employee_id: str,
        assigned_to_employee_id: str | None = None,
        subject_type: str = "NONE",
        subject_id: str | None = None,
        priority: str = "NORMAL",
    ) -> ManualTask:
        task = validate_manual_task(
            ManualTask(
                task_id=self._id_factory(),
                title=normalize_manual_task_title(title),
                description=normalize_manual_task_description(description),
                due_at=due_at,
                created_at=self._now(),
                completed_at=None,
                created_by_employee_id=created_by_employee_id,
                assigned_to_employee_id=assigned_to_employee_id,
                subject_type=validate_manual_task_subject_type(subject_type),
                subject_id=subject_id,
                priority=validate_manual_task_priority(priority),
            )
        )
        self._validate_employee(task.created_by_employee_id, "created_by_employee_id")
        if task.assigned_to_employee_id is not None:
            self._validate_employee(
                task.assigned_to_employee_id, "assigned_to_employee_id"
            )
        self._validate_subject(task.subject_type, task.subject_id)
        self._repository.save(task)
        return task

    def get_task(self, task_id: str) -> ManualTask | None:
        return self._repository.get(task_id)

    def list_open_tasks(self) -> list[ManualTask]:
        return self._repository.list_open()

    def list_tasks_for_subject(
        self, subject_type: str, subject_id: str
    ) -> list[ManualTask]:
        typed_subject = validate_manual_task_subject_type(subject_type)
        if typed_subject == "NONE":
            raise ValueError("subject_type NONE has no subject task list")
        return self._repository.list_for_subject(typed_subject, subject_id)

    def complete_task(
        self, task_id: str, *, completed_at: datetime | None = None
    ) -> ManualTask:
        current = self._repository.get(task_id)
        if current is None:
            raise KeyError(task_id)
        if current.completed_at is not None:
            return current
        timestamp = completed_at or self._now()
        validate_manual_task(replace(current, completed_at=timestamp))
        return self._repository.complete(task_id, timestamp)

    def _validate_employee(self, employee_id: str, field: str) -> None:
        if not self._employee_exists(employee_id):
            raise ValueError(f"{field} does not reference an existing employee")

    def _validate_subject(
        self, subject_type: ManualTaskSubjectType, subject_id: str | None
    ) -> None:
        if subject_type == "NONE":
            return
        assert subject_id is not None
        if not self._subject_exists(subject_type, subject_id):
            raise ValueError("subject_id does not reference an existing subject")


def _subject_exists_default(
    _subject_type: ManualTaskSubjectType, _subject_id: str
) -> bool:
    return True
