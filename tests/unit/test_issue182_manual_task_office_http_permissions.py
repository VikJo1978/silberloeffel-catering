from __future__ import annotations

import urllib.parse

from tests.unit.test_issue182_manual_task_office_http import (
    _cookie_value,
    _login,
    _request,
    issue182_panel,
)


def test_superadmin_sees_manual_and_existing_system_tasks(issue182_panel) -> None:
    jar = _login(issue182_panel, "issue182.admin", "ChangedPassw0rd!")

    status, body, _headers = _request(issue182_panel.base, "/aufgaben", jar=jar)

    assert status == 200
    assert "Manuelle Aufgaben" in body
    assert "Automatisch abgeleitete Aufgaben" in body
    assert "Neue Aufgabe" in body
    assert 'name="assigned_to_employee_id"' in body


def test_view_only_employee_cannot_create_manual_task(issue182_panel) -> None:
    jar = _login(issue182_panel, "issue182.assignee", "AssigneePassw0rd!")
    csrf = _cookie_value(jar, "sl_employee_csrf")

    status, _body, _headers = _request(
        issue182_panel.base,
        "/aufgaben/manual",
        method="POST",
        data={
            "_csrf_token": csrf,
            "title": "Darf nicht angelegt werden",
            "description": "",
            "due_at": "",
            "assigned_to_employee_id": "",
            "subject_type": "NONE",
            "subject_id": "",
        },
        jar=jar,
    )

    assert status == 403


def test_superadmin_can_create_unassigned_subject_task(issue182_panel) -> None:
    jar = _login(issue182_panel, "issue182.admin", "ChangedPassw0rd!")
    csrf = _cookie_value(jar, "sl_employee_csrf")

    status, _body, headers = _request(
        issue182_panel.base,
        "/aufgaben/manual",
        method="POST",
        data={
            "_csrf_token": csrf,
            "title": "Auftrag prüfen",
            "description": "Ohne Zuweisung",
            "due_at": "",
            "assigned_to_employee_id": "",
            "subject_type": "ORDER",
            "subject_id": "order-182",
        },
        jar=jar,
    )

    assert status == 303
    assert headers["Location"] == "/aufgaben?msg=created"

    status, body, _headers = _request(issue182_panel.base, "/aufgaben", jar=jar)
    assert status == 200
    assert "Auftrag prüfen" in body
    assert "Nicht zugewiesen" in body
    assert "Auftrag · order-182" in body


def test_completion_route_rejects_unknown_task_id(issue182_panel) -> None:
    jar = _login(issue182_panel, "issue182.admin", "ChangedPassw0rd!")
    csrf = _cookie_value(jar, "sl_employee_csrf")
    missing_id = urllib.parse.quote("missing-task-182", safe="")

    status, _body, _headers = _request(
        issue182_panel.base,
        f"/aufgaben/manual/{missing_id}/complete",
        method="POST",
        data={"_csrf_token": csrf},
        jar=jar,
    )

    assert status in {400, 404}
