from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
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
    priority_label,
    sort_task_rows,
    subject_permission,
    system_task_priority,
)
from catering_system.ui.office_panel_dashboard import _task_rows
from catering_system.ui.office_panel_tasks_list import (
    _format_due,
    _subject_cell,
    render_aufgaben_list,
)
from catering_system.ui.office_panel_views import OfficePageContext

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
    assert system_task_priority({"category": "payment", "urgency": "overdue"}) == "HIGH"


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
            row[1]
            for row in repo._conn.execute("PRAGMA table_info(manual_tasks)").fetchall()
        }
        assert "priority" in columns
        version = repo._conn.execute(
            "SELECT version FROM schema_migrations WHERE component='manual_tasks' ORDER BY version DESC LIMIT 1"
        ).fetchone()
        assert version == (2,)
    finally:
        repo.close()


def test_presentation_helpers_cover_invalid_and_mixed_date_inputs() -> None:
    assert priority_label("HIGH") == "Hoch"
    assert priority_label("unexpected") == "Normal"
    assert subject_permission("OFFER") == "offers.view"
    assert subject_permission("NONE") is None
    assert parse_subject_reference("") == ("NONE", None)

    with pytest.raises(ValueError, match="subject type"):
        make_subject_reference("NONE", "x")
    with pytest.raises(ValueError, match="subject key"):
        make_subject_reference("OFFER", "")
    for invalid in ("OFFER:", "BOGUS:abc", "not-a-reference"):
        with pytest.raises(ValueError, match="subject reference"):
            parse_subject_reference(invalid)

    rows = [
        {
            "task_id": "none",
            "priority": "NORMAL",
            "due_at": None,
            "opened_at": None,
        },
        {
            "task_id": "naive-datetime",
            "priority": "NORMAL",
            "due_at": datetime(2026, 8, 28, 10, 0),
            "opened_at": datetime(2026, 8, 1, 10, 0),
        },
        {
            "task_id": "aware-datetime",
            "priority": "NORMAL",
            "due_at": _NOW,
            "opened_at": _NOW,
        },
        {
            "task_id": "date",
            "priority": "NORMAL",
            "due_at": date(2026, 8, 29),
            "opened_at": date(2026, 8, 2),
        },
        {
            "task_id": "datetime-string",
            "priority": "NORMAL",
            "due_at": "2026-08-30T12:00:00+02:00",
            "opened_at": "2026-08-03T12:00:00",
        },
        {
            "task_id": "date-string",
            "priority": "NORMAL",
            "due_at": "2026-08-31",
            "opened_at": "2026-08-04",
        },
        {
            "task_id": "invalid-string",
            "priority": "NORMAL",
            "due_at": "not-a-date",
            "opened_at": "also-not-a-date",
        },
        {
            "task_id": "unsupported",
            "priority": "NORMAL",
            "due_at": 123,
            "opened_at": object(),
        },
    ]

    assert {row["task_id"] for row in sort_task_rows(rows)} == {
        row["task_id"] for row in rows
    }


def test_task_list_formats_due_subjects_and_manual_actions() -> None:
    assert _format_due(None) == "–"
    assert _format_due("2026-08-26") == "26.08.2026"
    assert _format_due("not-a-date") == "not-a-date"
    assert _format_due(datetime(2026, 8, 27, 23, 0, tzinfo=UTC)) == "28.08.2026"
    assert _format_due(date(2026, 8, 28)) == "28.08.2026"
    assert _format_due(object()) == "–"

    linked = _subject_cell(
        {"subject_label": "Angebot <Test>", "subject_href": "/offer/<id>"}
    )
    assert "Angebot &lt;Test&gt;" in linked
    assert "/offer/&lt;id&gt;" in linked
    assert _subject_cell({"subject_label": "–"}) == "–"

    context = OfficePageContext(csrf_token="csrf")
    html = render_aufgaben_list(
        [
            {
                "kind": "manual",
                "type_label": "Manuell",
                "priority": "HIGH",
                "title": "Anrufen",
                "description": "Kunde",
                "subject_label": "Angebot ABC",
                "subject_href": "/offer/abc",
                "due_at": "2026-08-26",
                "assigned_to": "Viktor",
                "task_id": "task-1",
                "can_complete": False,
            },
            {
                "kind": "system",
                "type_label": "System",
                "priority": "LOW",
                "title": "Prüfen",
                "description": "–",
                "subject_label": "–",
                "subject_href": "",
                "due_at": None,
                "assigned_to": "–",
                "task_id": "system-1",
                "action_href": "/inquiry/abc",
                "action_label": "Anfrage öffnen",
            },
        ],
        context=context,
        assignee_options=[{"id": "emp-1", "display_name": "Mitarbeiter"}],
        subject_options=[{"value": "OFFER:abc", "label": "Angebot ABC"}],
        can_create_manual_task=True,
        can_assign_manual_task=True,
        create_form_fields='<input type="hidden" name="test" value="1">',
    )
    assert "Wichtigkeit" in html
    assert "Angebot ABC" in html
    assert "Mitarbeiter" in html
    assert "Erledigt" not in html
    assert "Anfrage öffnen" in html


def test_dashboard_manual_row_shows_priority_before_subtitle() -> None:
    html = _task_rows(
        [
            {
                "category": "manual",
                "title": "Kunden anrufen",
                "subtitle": "Angebot ABC",
                "priority_label": "Hoch",
                "action_href": "/offer/abc",
                "action_label": "Bezug öffnen",
            }
        ]
    )
    assert "Hoch · Angebot ABC" in html
    assert "Bezug öffnen" in html


def test_sqlite_rejects_migration_name_mismatch(tmp_path: Path) -> None:
    db = tmp_path / "mismatch.db"
    repo = SQLiteManualTaskRepository(db)
    repo.close()
    connection = sqlite3.connect(db)
    connection.execute(
        "UPDATE schema_migrations SET name='wrong' "
        "WHERE component='manual_tasks' AND version=2"
    )
    connection.commit()
    connection.close()

    with pytest.raises(RuntimeError, match="migration 2 name mismatch"):
        SQLiteManualTaskRepository(db)


def test_sqlite_from_connection_migrates_inside_existing_transaction(
    tmp_path: Path,
) -> None:
    connection = sqlite3.connect(tmp_path / "transaction.db")
    connection.execute("BEGIN")
    repo = SQLiteManualTaskRepository.from_connection(connection)
    try:
        versions = repo._conn.execute(
            "SELECT version FROM schema_migrations "
            "WHERE component='manual_tasks' ORDER BY version"
        ).fetchall()
        assert versions == [(1,), (2,)]
    finally:
        repo.close()


def test_sqlite_offer_subject_errors_are_explicit(tmp_path: Path) -> None:
    offer_id = str(uuid.uuid4())
    task = ManualTask(
        task_id=str(uuid.uuid4()),
        title="Offer task",
        description="",
        due_at=None,
        created_at=_NOW,
        completed_at=None,
        created_by_employee_id=str(uuid.uuid4()),
        assigned_to_employee_id=None,
        subject_type="OFFER",
        subject_id=offer_id,
        priority="HIGH",
    )

    missing_table_repo = SQLiteManualTaskRepository(tmp_path / "missing-table.db")
    try:
        with pytest.raises(
            sqlite3.IntegrityError, match="subject table does not exist"
        ):
            missing_table_repo.save(task)
    finally:
        missing_table_repo.close()

    missing_row_repo = SQLiteManualTaskRepository(tmp_path / "missing-row.db")
    try:
        missing_row_repo._conn.execute(
            "CREATE TABLE offers (offer_id TEXT PRIMARY KEY)"
        )
        with pytest.raises(sqlite3.IntegrityError, match="subject does not exist"):
            missing_row_repo.save(task)
    finally:
        missing_row_repo.close()
