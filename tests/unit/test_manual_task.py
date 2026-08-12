from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from catering_system.domain.manual_task import (
    MAX_MANUAL_TASK_DESCRIPTION_LENGTH,
    MAX_MANUAL_TASK_TITLE_LENGTH,
    ManualTask,
    normalize_manual_task_description,
    normalize_manual_task_title,
    validate_manual_task,
    validate_manual_task_subject_type,
)
from catering_system.repositories.in_memory_manual_task_repository import (
    InMemoryManualTaskRepository,
)
from catering_system.services.manual_task_service import ManualTaskService

_NOW = datetime(2026, 8, 9, 8, 0, tzinfo=UTC)
_DONE = datetime(2026, 8, 9, 9, 0, tzinfo=UTC)
_TASK_ID = "11111111-1111-4111-8111-111111111111"
_TASK_ID_2 = "22222222-2222-4222-8222-222222222222"
_EMPLOYEE_ID = "33333333-3333-4333-8333-333333333333"
_ASSIGNEE_ID = "44444444-4444-4444-8444-444444444444"
_ORDER_ID = "55555555-5555-4555-8555-555555555555"
_INQUIRY_ID = "66666666-6666-4666-8666-666666666666"
_CONTACT_ID = "77777777-7777-4777-8777-777777777777"


class IdSequence:
    def __init__(self, *values: str) -> None:
        self._values = list(values)

    def __call__(self) -> str:
        return self._values.pop(0)


def _service(
    repo: InMemoryManualTaskRepository | None = None,
    *,
    employee_ids: set[str] | None = None,
    subject_ids: set[tuple[str, str]] | None = None,
    id_factory=None,
) -> ManualTaskService:
    employees = (
        employee_ids if employee_ids is not None else {_EMPLOYEE_ID, _ASSIGNEE_ID}
    )
    subjects = (
        subject_ids
        if subject_ids is not None
        else {
            ("ORDER", _ORDER_ID),
            ("INQUIRY", _INQUIRY_ID),
            ("CONTACT", _CONTACT_ID),
        }
    )
    return ManualTaskService(
        repo or InMemoryManualTaskRepository(),
        employee_exists=lambda employee_id: employee_id in employees,
        subject_exists=lambda subject_type, subject_id: (
            (
                subject_type,
                subject_id,
            )
            in subjects
        ),
        id_factory=id_factory or IdSequence(_TASK_ID, _TASK_ID_2),
        now=lambda: _NOW,
    )


def test_valid_unlinked_task_normalizes_description_and_derives_open_status() -> None:
    service = _service()

    task = service.create_task(
        title="  Angebot nachfassen  ",
        description=None,
        created_by_employee_id=_EMPLOYEE_ID,
    )

    assert task.task_id == _TASK_ID
    assert task.title == "Angebot nachfassen"
    assert task.description == ""
    assert task.created_at == _NOW
    assert task.completed_at is None
    assert task.status == "OPEN"
    assert task.subject_type == "NONE"
    assert task.subject_id is None


@pytest.mark.parametrize(
    ("subject_type", "subject_id"),
    [
        ("ORDER", _ORDER_ID),
        ("INQUIRY", _INQUIRY_ID),
        ("CONTACT", _CONTACT_ID),
    ],
)
def test_typed_subject_task(subject_type: str, subject_id: str) -> None:
    service = _service()

    task = service.create_task(
        title="Prüfen",
        description="  vor Ort klären  ",
        due_at=_NOW + timedelta(days=1),
        created_by_employee_id=_EMPLOYEE_ID,
        subject_type=subject_type,
        subject_id=subject_id,
    )

    assert task.description == "vor Ort klären"
    assert task.due_at == _NOW + timedelta(days=1)
    assert task.subject_type == subject_type
    assert task.subject_id == subject_id


def test_none_with_subject_id_rejected() -> None:
    with pytest.raises(ValueError, match="subject_id must be null"):
        _service().create_task(
            title="Prüfen",
            created_by_employee_id=_EMPLOYEE_ID,
            subject_type="NONE",
            subject_id=_ORDER_ID,
        )


def test_typed_subject_without_id_rejected() -> None:
    with pytest.raises(ValueError, match="subject_id is required"):
        _service().create_task(
            title="Prüfen",
            created_by_employee_id=_EMPLOYEE_ID,
            subject_type="ORDER",
        )


def test_invalid_subject_identity_rejected_by_service() -> None:
    with pytest.raises(ValueError, match="existing subject"):
        _service(subject_ids=set()).create_task(
            title="Prüfen",
            created_by_employee_id=_EMPLOYEE_ID,
            subject_type="ORDER",
            subject_id=_ORDER_ID,
        )


def test_creator_identity_required_and_assignee_optional() -> None:
    service = _service(employee_ids={_EMPLOYEE_ID})

    task = service.create_task(
        title="Prüfen",
        created_by_employee_id=_EMPLOYEE_ID,
    )

    assert task.created_by_employee_id == _EMPLOYEE_ID
    assert task.assigned_to_employee_id is None
    with pytest.raises(ValueError, match="assigned_to_employee_id"):
        service.create_task(
            title="Prüfen",
            created_by_employee_id=_EMPLOYEE_ID,
            assigned_to_employee_id=_ASSIGNEE_ID,
        )


def test_optional_assignee_persisted() -> None:
    service = _service()

    task = service.create_task(
        title="Prüfen",
        created_by_employee_id=_EMPLOYEE_ID,
        assigned_to_employee_id=_ASSIGNEE_ID,
    )

    assert task.assigned_to_employee_id == _ASSIGNEE_ID
    assert service.get_task(task.task_id) == task


def test_completion_is_additive_idempotent_and_excluded_from_open() -> None:
    repo = InMemoryManualTaskRepository()
    service = _service(repo)
    task = service.create_task(title="Prüfen", created_by_employee_id=_EMPLOYEE_ID)

    completed = service.complete_task(task.task_id, completed_at=_DONE)
    repeated = service.complete_task(
        task.task_id, completed_at=_DONE + timedelta(hours=1)
    )

    assert completed.completed_at == _DONE
    assert completed.status == "DONE"
    assert repeated.completed_at == _DONE
    assert service.list_open_tasks() == []


def test_list_for_subject_returns_only_matching_tasks() -> None:
    repo = InMemoryManualTaskRepository()
    service = _service(repo)
    order_task = service.create_task(
        title="Order",
        created_by_employee_id=_EMPLOYEE_ID,
        subject_type="ORDER",
        subject_id=_ORDER_ID,
    )
    service.create_task(
        title="Inquiry",
        created_by_employee_id=_EMPLOYEE_ID,
        subject_type="INQUIRY",
        subject_id=_INQUIRY_ID,
    )

    assert service.list_tasks_for_subject("ORDER", _ORDER_ID) == [order_task]


def test_invalid_uuid4_and_non_utc_timestamp_rejected() -> None:
    service = _service(id_factory=IdSequence("not-a-uuid"))
    with pytest.raises(ValueError, match="UUID"):
        service.create_task(title="Prüfen", created_by_employee_id=_EMPLOYEE_ID)

    local_time = _NOW.replace(tzinfo=None)
    with pytest.raises(ValueError, match="UTC"):
        _service().create_task(
            title="Prüfen",
            created_by_employee_id=_EMPLOYEE_ID,
            due_at=local_time,
        )


def test_domain_rejects_invalid_subject_type() -> None:
    with pytest.raises(ValueError, match="subject_type"):
        validate_manual_task_subject_type("PROJECT")


def test_domain_rejects_invalid_title_and_description_shapes() -> None:
    with pytest.raises(TypeError, match="title"):
        normalize_manual_task_title(42)
    with pytest.raises(ValueError, match="empty"):
        normalize_manual_task_title(" ")
    with pytest.raises(ValueError, match="at most"):
        normalize_manual_task_title("x" * (MAX_MANUAL_TASK_TITLE_LENGTH + 1))

    with pytest.raises(TypeError, match="description"):
        normalize_manual_task_description(42)
    with pytest.raises(ValueError, match="at most"):
        normalize_manual_task_description(
            "x" * (MAX_MANUAL_TASK_DESCRIPTION_LENGTH + 1)
        )


def test_domain_rejects_invalid_employee_and_completion_values() -> None:
    valid = ManualTask(
        task_id=_TASK_ID,
        title="Prüfen",
        description="",
        due_at=None,
        created_at=_NOW,
        completed_at=None,
        created_by_employee_id=_EMPLOYEE_ID,
        assigned_to_employee_id=None,
        subject_type="NONE",
        subject_id=None,
    )

    with pytest.raises(ValueError, match="completed_at"):
        validate_manual_task(
            ManualTask(
                **{
                    **valid.__dict__,
                    "completed_at": _NOW - timedelta(minutes=1),
                }
            )
        )
    with pytest.raises(TypeError, match="created_by_employee_id"):
        validate_manual_task(
            ManualTask(**{**valid.__dict__, "created_by_employee_id": 42})
        )
    with pytest.raises(ValueError, match="created_by_employee_id"):
        validate_manual_task(
            ManualTask(**{**valid.__dict__, "created_by_employee_id": " "})
        )


def test_domain_rejects_non_string_non_v4_and_non_canonical_uuid() -> None:
    valid = ManualTask(
        task_id=_TASK_ID,
        title="Prüfen",
        description="",
        due_at=None,
        created_at=_NOW,
        completed_at=None,
        created_by_employee_id=_EMPLOYEE_ID,
        assigned_to_employee_id=None,
        subject_type="NONE",
        subject_id=None,
    )

    with pytest.raises(TypeError, match="UUID string"):
        validate_manual_task(ManualTask(**{**valid.__dict__, "task_id": 42}))
    with pytest.raises(ValueError, match="UUID4"):
        validate_manual_task(
            ManualTask(
                **{
                    **valid.__dict__,
                    "task_id": "11111111-1111-1111-8111-111111111111",
                }
            )
        )
    with pytest.raises(ValueError, match="canonical"):
        validate_manual_task(
            ManualTask(
                **{
                    **valid.__dict__,
                    "task_id": "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA",
                }
            )
        )


def test_in_memory_repository_rejects_completion_rewrite_and_missing_completion() -> (
    None
):
    repo = InMemoryManualTaskRepository()
    task = _service(repo).create_task(
        title="Prüfen", created_by_employee_id=_EMPLOYEE_ID
    )
    completed = repo.complete(task.task_id, _DONE)

    assert repo.complete(task.task_id, _DONE + timedelta(hours=1)) == completed
    with pytest.raises(ValueError, match="completion"):
        repo.save(
            ManualTask(
                **{**completed.__dict__, "completed_at": _DONE + timedelta(hours=2)}
            )
        )
    with pytest.raises(KeyError):
        repo.complete(_TASK_ID_2, _DONE)


def test_service_rejects_none_subject_listing_and_missing_completion() -> None:
    service = _service()

    with pytest.raises(ValueError, match="NONE"):
        service.list_tasks_for_subject("NONE", _TASK_ID)
    with pytest.raises(KeyError):
        service.complete_task(_TASK_ID)


def test_service_default_subject_checker_allows_typed_subject() -> None:
    service = ManualTaskService(
        InMemoryManualTaskRepository(),
        employee_exists=lambda employee_id: employee_id == _EMPLOYEE_ID,
        id_factory=IdSequence(_TASK_ID),
        now=lambda: _NOW,
    )

    task = service.create_task(
        title="Prüfen",
        created_by_employee_id=_EMPLOYEE_ID,
        subject_type="ORDER",
        subject_id=_ORDER_ID,
    )

    assert task.subject_id == _ORDER_ID
