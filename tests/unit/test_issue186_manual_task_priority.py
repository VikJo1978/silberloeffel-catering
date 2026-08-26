from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from catering_system.domain.manual_task import ManualTask
from catering_system.repositories.in_memory_manual_task_repository import (
    InMemoryManualTaskRepository,
)
from catering_system.repositories.sqlite_manual_task_repository import (
    SQLiteManualTaskRepository,
)
from catering_system.ui.manual_task_presentation import (
    make_subject_reference,
    parse_subject_reference,
    sort_task_rows,
    system_task_priority,
)

_NOW = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)


def _task(*, priority: str, due_days: int, title: str) -> ManualTask:
    return ManualTask(
        task_id=str(uuid.uuid4()),
        title=title,
        description="",
        due_at=_NOW + timedelta(days=due_days),
        created_at=_NOW,
        completed_at=None,
        created_by_employee_id=str(uuid.uuid4()),
        assigned_to_employee_id=None,
        subject_type="NONE",
        subject_id=None,
        priority=priority,  # type: ignore[arg-type]
    )


def test_manual_priority_is_stronger_than_due_date() -> None:
    repo = InMemoryManualTaskRepository()
    low_early = _task(priority="LOW", due_days=0, title="low early")
    high_late = _task(priority="HIGH", due_days=30, title="high late")
    normal_middle = _task(priority="NORMAL", due_days=1, title="normal middle")
    for task in (low_early, high_late, normal_middle):
        repo.save(task)

    assert [task.title for task in repo.list_open()] == [
        "high late",
        "normal middle",
        "low early",
    ]


def test_combined_rows_rank_priority_before_date() -> None:
    rows = [
        {
            "task_id": "low",
            "category": "manual",
            "priority": "LOW",
            "due_at": "2026-08-26",
        },
        {
            "task_id": "high",
            "category": "verify",
            "priority": "HIGH",
            "due_at": "2026-09-30",
        },
        {
            "task_id": "normal",
            "category": "payment",
            "priority": "NORMAL",
            "due_at": "2026-08-27",
        },
    ]
    assert [row["task_id"] for row in sort_task_rows(rows)] == [
        "high",
        "normal",
        "low",
    ]


def test_system_task_importance_mapping() -> None:
    assert system_task_priority({"category": "verify", "urgency": "normal"}) == "HIGH"
    assert (
        system_task_priority({"category": "prepare_offer", "urgency": "normal"})
        == "LOW"
    )
    assert (
        system_task_priority({"category": "payment", "urgency": "overdue"})
        == "HIGH"
    )


def test_subject_reference_supports_offer_and_opaque_contact_keys() -> None:
    offer_id = str(uuid.uuid4())
    assert parse_subject_reference(make_subject_reference("OFFER", offer_id)) == (
        "OFFER",
        offer_id,
    )
    contact_key = "intake:email:foo+bar@example.test"
    assert parse_subject_reference(make_subject_reference("CONTACT", contact_key)) == (
        "CONTACT",
        contact_key,
    )


def test_sqlite_v1_migration_preserves_task_and_defaults_normal(tmp_path: Path) -> None:
    db = tmp_path / "core.db"
    task_id = str(uuid.uuid4())
    employee_id = str(uuid.uuid4())
    connection = sqlite3.connect(db)
    connection.executescript(
        """
        CREATE TABLE schema_migrations (
            component TEXT NOT NULL,
            version INTEGER NOT NULL,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL,
            PRIMARY KEY (component, version)
        );
        INSERT INTO schema_migrations(component, version, name, applied_at)
        VALUES ('manual_tasks', 1, 'create_manual_tasks', '2026-08-01T00:00:00Z');
        CREATE TABLE manual_tasks (
            task_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            due_at TEXT,
            created_at TEXT NOT NULL,
            completed_at TEXT,
            created_by_employee_id TEXT NOT NULL,
            assigned_to_employee_id TEXT,
            subject_type TEXT NOT NULL,
            subject_id TEXT,
            CHECK (subject_type IN ('NONE', 'ORDER', 'INQUIRY', 'CONTACT')),
            CHECK (
                (subject_type = 'NONE' AND subject_id IS NULL)
                OR (subject_type <> 'NONE' AND subject_id IS NOT NULL)
            )
        );
        """
    )
    connection.execute(
        """
        INSERT INTO manual_tasks(
            task_id, title, description, due_at, created_at, completed_at,
            created_by_employee_id, assigned_to_employee_id, subject_type, subject_id
        ) VALUES (?, 'legacy', '', NULL, ?, NULL, ?, NULL, 'NONE', NULL)
        """,
        (task_id, _NOW.isoformat(), employee_id),
    )
    connection.commit()
    connection.close()

    repo = SQLiteManualTaskRepository(db)
    try:
        migrated = repo.get(task_id)
        assert migrated is not None
        assert migrated.priority == "NORMAL"
        columns = {
            row[1] for row in repo._conn.execute("PRAGMA table_info(manual_tasks)").fetchall()
        }
        assert "priority" in columns
        version = repo._conn.execute(
            "SELECT version FROM schema_migrations WHERE component='manual_tasks' ORDER BY version DESC LIMIT 1"
        ).fetchone()
        assert version == (2,)
    finally:
        repo.close()
