from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from catering_system.domain.contact_profile import ContactProfile
from catering_system.domain.inquiry import Inquiry
from catering_system.domain.manual_task import ManualTask
from catering_system.domain.order import Order, OrderVersion
from catering_system.repositories.sqlite_contact_profile_repository import (
    SQLiteContactProfileRepository,
)
from catering_system.repositories.sqlite_inquiry_repository import (
    SQLiteInquiryRepository,
)
from catering_system.repositories.sqlite_manual_task_repository import (
    SQLiteManualTaskRepository,
)
from catering_system.repositories.sqlite_order_repository import SQLiteOrderRepository

_NOW = datetime(2026, 8, 9, 8, 0, tzinfo=UTC)
_DONE = datetime(2026, 8, 9, 9, 0, tzinfo=UTC)
_TASK_ID = "11111111-1111-4111-8111-111111111111"
_TASK_ID_2 = "22222222-2222-4222-8222-222222222222"
_EMPLOYEE_ID = "33333333-3333-4333-8333-333333333333"
_ASSIGNEE_ID = "44444444-4444-4444-8444-444444444444"
_ORDER_ID = "55555555-5555-4555-8555-555555555555"
_ORDER_VERSION_ID = "55555555-5555-4555-8555-555555555556"
_INQUIRY_ID = "66666666-6666-4666-8666-666666666666"
_CONTACT_ID = "77777777-7777-4777-8777-777777777777"


def _task(
    task_id: str = _TASK_ID,
    *,
    title: str = "Prüfen",
    description: str = "",
    due_at: datetime | None = None,
    completed_at: datetime | None = None,
    created_by_employee_id: str = _EMPLOYEE_ID,
    assigned_to_employee_id: str | None = None,
    subject_type: str = "NONE",
    subject_id: str | None = None,
) -> ManualTask:
    return ManualTask(
        task_id=task_id,
        title=title,
        description=description,
        due_at=due_at,
        created_at=_NOW,
        completed_at=completed_at,
        created_by_employee_id=created_by_employee_id,
        assigned_to_employee_id=assigned_to_employee_id,
        subject_type=subject_type,  # type: ignore[arg-type]
        subject_id=subject_id,
    )


def _seed_inquiry(repo: SQLiteInquiryRepository) -> Inquiry:
    inquiry = Inquiry(
        inquiry_id=_INQUIRY_ID,
        event_date=date(2026, 9, 1),
        created_at=_NOW,
        updated_at=_NOW,
        inquiry_source="manual",
        crm_stage="Neue Anfrage",
        customer_linkage={},
        time_window_text="mittags",
        location_text="Hamburg",
        guest_count_estimate=20,
        planning_mode="caterer_suggestion",
        call_verification_required=False,
        call_verification_status="not_required",
    )
    repo.save(inquiry)
    return inquiry


def _seed_order(repo: SQLiteOrderRepository) -> Order:
    order = Order(
        order_id=_ORDER_ID,
        source_inquiry_id=_INQUIRY_ID,
        created_at=_NOW,
        updated_at=_NOW,
    )
    version = OrderVersion(
        order_version_id=_ORDER_VERSION_ID,
        order_id=_ORDER_ID,
        version_number=1,
        created_at=_NOW,
        event_date=date(2026, 9, 1),
        time_window_text="mittags",
        location_text="Hamburg",
        guest_count_estimate=20,
        planning_mode="caterer_suggestion",
    )
    repo.save_order_with_initial_version(order, version)
    return order


def _seed_contact(repo: SQLiteContactProfileRepository) -> ContactProfile:
    profile = ContactProfile(
        contact_profile_id=_CONTACT_ID,
        display_name="Kunde",
        email=None,
        phone=None,
        created_at=_NOW,
        updated_at=_NOW,
    )
    repo.create_profile(profile)
    return profile


def _open_seeded(
    db: Path,
) -> tuple[
    SQLiteManualTaskRepository,
    SQLiteInquiryRepository,
    SQLiteOrderRepository,
    SQLiteContactProfileRepository,
]:
    inquiries = SQLiteInquiryRepository(db)
    _seed_inquiry(inquiries)
    inquiries.close()
    orders = SQLiteOrderRepository(db)
    _seed_order(orders)
    orders.close()
    contacts = SQLiteContactProfileRepository(db)
    _seed_contact(contacts)
    contacts.close()
    return (
        SQLiteManualTaskRepository(db),
        SQLiteInquiryRepository(db),
        SQLiteOrderRepository(db),
        SQLiteContactProfileRepository(db),
    )


def test_sqlite_migration_is_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "core.db"
    repo = SQLiteManualTaskRepository(db)
    repo.close()

    reopened = SQLiteManualTaskRepository(db)
    try:
        rows = reopened._conn.execute(
            """
            SELECT version, name FROM schema_migrations
            WHERE component = 'manual_tasks'
            """
        ).fetchall()
        assert rows == [
            (1, "create_manual_tasks"),
            (2, "add_priority_and_offer_subject"),
        ]
    finally:
        reopened.close()


def test_sqlite_round_trip_unlinked_and_assignee(tmp_path: Path) -> None:
    repo = SQLiteManualTaskRepository(tmp_path / "core.db")
    task = _task(
        description="Notiz",
        due_at=_NOW + timedelta(days=1),
        assigned_to_employee_id=_ASSIGNEE_ID,
    )

    repo.save(task)

    assert repo.get(task.task_id) == task
    assert repo.list_open() == [task]
    repo.close()


@pytest.mark.parametrize(
    ("subject_type", "subject_id"),
    [
        ("ORDER", _ORDER_ID),
        ("INQUIRY", _INQUIRY_ID),
        ("CONTACT", _CONTACT_ID),
    ],
)
def test_sqlite_subject_tasks_round_trip(
    tmp_path: Path, subject_type: str, subject_id: str
) -> None:
    repo, inquiries, orders, contacts = _open_seeded(tmp_path / "core.db")
    try:
        task = _task(subject_type=subject_type, subject_id=subject_id)
        repo.save(task)

        assert repo.get(task.task_id) == task
        assert repo.list_for_subject(task.subject_type, subject_id) == [task]
    finally:
        repo.close()
        inquiries.close()
        orders.close()
        contacts.close()


def test_sqlite_rejects_invalid_subject_identity(tmp_path: Path) -> None:
    repo, inquiries, orders, contacts = _open_seeded(tmp_path / "core.db")
    try:
        with pytest.raises(sqlite3.IntegrityError, match="order subject"):
            repo.save(
                _task(
                    subject_type="ORDER",
                    subject_id="99999999-9999-4999-8999-999999999999",
                )
            )
    finally:
        repo.close()
        inquiries.close()
        orders.close()
        contacts.close()


def test_sqlite_completion_is_additive_and_no_rewrite(tmp_path: Path) -> None:
    repo = SQLiteManualTaskRepository(tmp_path / "core.db")
    task = _task()
    repo.save(task)

    completed = repo.complete(task.task_id, _DONE)
    repeated = repo.complete(task.task_id, _DONE + timedelta(hours=1))

    assert completed.completed_at == _DONE
    assert repeated.completed_at == _DONE
    assert repo.list_open() == []
    with pytest.raises(sqlite3.IntegrityError, match="completion"):
        repo.save(_task(completed_at=_DONE + timedelta(hours=2)))
    repo.close()


def test_sqlite_list_for_subject_returns_only_matching_tasks(tmp_path: Path) -> None:
    repo, inquiries, orders, contacts = _open_seeded(tmp_path / "core.db")
    try:
        order_task = _task(
            task_id=_TASK_ID,
            title="Order",
            subject_type="ORDER",
            subject_id=_ORDER_ID,
        )
        inquiry_task = _task(
            task_id=_TASK_ID_2,
            title="Inquiry",
            subject_type="INQUIRY",
            subject_id=_INQUIRY_ID,
        )
        repo.save(order_task)
        repo.save(inquiry_task)

        assert repo.list_for_subject("ORDER", _ORDER_ID) == [order_task]
    finally:
        repo.close()
        inquiries.close()
        orders.close()
        contacts.close()


def test_sqlite_from_connection_uses_existing_transaction_scope() -> None:
    connection = sqlite3.connect(":memory:")
    repo = SQLiteManualTaskRepository.from_connection(connection)
    task = _task()

    repo.save(task)

    assert repo.get(task.task_id) == task
    repo.close()


def test_sqlite_complete_missing_task_raises_key_error(tmp_path: Path) -> None:
    repo = SQLiteManualTaskRepository(tmp_path / "core.db")
    try:
        with pytest.raises(KeyError):
            repo.complete(_TASK_ID, _DONE)
    finally:
        repo.close()


def test_sqlite_rejects_typed_subject_when_subject_table_missing(
    tmp_path: Path,
) -> None:
    repo = SQLiteManualTaskRepository(tmp_path / "core.db")
    try:
        with pytest.raises(sqlite3.IntegrityError, match="subject table"):
            repo.save(_task(subject_type="ORDER", subject_id=_ORDER_ID))
    finally:
        repo.close()
