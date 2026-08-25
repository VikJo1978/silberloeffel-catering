from __future__ import annotations

from datetime import UTC, datetime

from catering_system.ui.office_panel_tasks_list import (
    ManualTaskViewRow,
    render_aufgaben_list,
)
from catering_system.ui.office_panel_views import OfficePageContext


def _context(*permissions: str) -> OfficePageContext:
    return OfficePageContext(
        rueckruf_count=None,
        csrf_token="csrf-test",
        employee_effective_permissions=frozenset(permissions),
    )


def test_manual_task_ui_renders_create_assignment_and_complete_controls() -> None:
    html = render_aufgaben_list(
        [],
        context=_context(
            "tasks.view", "tasks.create", "tasks.assign", "tasks.complete"
        ),
        manual_tasks=[
            ManualTaskViewRow(
                task_id="550e8400-e29b-41d4-a716-446655440000",
                title="Kunden anrufen",
                description="Termin bestätigen",
                due_at=datetime(2026, 8, 26, 10, 30, tzinfo=UTC),
                assigned_to_label="Manual Worker",
                subject_type="NONE",
                subject_id=None,
            )
        ],
        can_create_manual=True,
        can_complete_manual=True,
        can_assign_manual=True,
        assignee_options=[("employee-1", "Manual Worker")],
        show_system_tasks=False,
    )

    assert 'action="/aufgaben/manual"' in html
    assert 'name="assigned_to_employee_id"' in html
    assert "Kunden anrufen" in html
    assert "Manual Worker" in html
    assert "/complete" in html
    assert "csrf-test" in html
    assert "Automatisch abgeleitete Aufgaben" not in html


def test_manual_task_ui_hides_mutations_without_permissions() -> None:
    html = render_aufgaben_list(
        [],
        context=_context("tasks.view"),
        manual_tasks=[
            ManualTaskViewRow(
                task_id="550e8400-e29b-41d4-a716-446655440000",
                title="Nur ansehen",
                description="",
                due_at=None,
                assigned_to_label="Nicht zugewiesen",
                subject_type="NONE",
                subject_id=None,
            )
        ],
        show_system_tasks=False,
    )

    assert "Neue Aufgabe" not in html
    assert "/complete" not in html
    assert "Nur ansehen" in html


def test_system_task_projection_remains_read_only_and_advisory() -> None:
    html = render_aufgaben_list(
        [
            {
                "urgency": "normal",
                "title": "Angebot prüfen",
                "subtitle": "Anfrage 123",
                "due_at": None,
                "action_href": "/inquiry/123",
                "action_label": "Öffnen",
            }
        ],
        context=_context("queue.view"),
        show_system_tasks=True,
    )

    assert "Automatisch abgeleitete Aufgaben" in html
    assert "Sie blockieren keine Entscheidung" in html
    assert "Angebot prüfen" in html
