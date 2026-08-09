"""Repository contract for persisted manual office tasks."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from catering_system.domain.manual_task import ManualTask, ManualTaskSubjectType


class ManualTaskRepository(Protocol):
    def get(self, task_id: str) -> ManualTask | None: ...

    def save(self, task: ManualTask) -> None: ...

    def list_open(self) -> list[ManualTask]: ...

    def list_for_subject(
        self, subject_type: ManualTaskSubjectType, subject_id: str
    ) -> list[ManualTask]: ...

    def complete(self, task_id: str, completed_at: datetime) -> ManualTask: ...
