from __future__ import annotations

import http.cookiejar
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from catering_system.domain.manual_task import ManualTask
from catering_system.repositories.in_memory_inquiry_repository import (
    InMemoryInquiryRepository,
)
from catering_system.repositories.in_memory_order_repository import (
    InMemoryOrderRepository,
)
from catering_system.ui.office_panel import OfficePanel
from catering_system.ui.office_panel_views import OfficePageContext
from tests.unit.test_office_panel_auth_2d1 import (
    PanelHarness,
    _create_employee,
    _create_panel,
    _csrf,
    _login,
    _ready_superadmin,
    _request,
    _shutdown,
)


@pytest.fixture()
def employee_panel(tmp_path: Path):
    panel = _create_panel(tmp_path, auth_mode="employee")
    yield panel
    _shutdown(panel)


def _login_employee(
    panel: PanelHarness,
    super_jar: http.cookiejar.CookieJar,
    *,
    username: str,
    permissions: frozenset[str],
) -> http.cookiejar.CookieJar:
    _create_employee(
        panel,
        super_jar,
        username=username,
        password="TaskTemp1!",
        role="USER",
        permissions=permissions,
    )
    return _login(panel, username=username, password="TaskTemp1!")


def test_aufgaben_requires_tasks_view_not_queue_view(
    employee_panel: PanelHarness,
) -> None:
    super_jar = _ready_superadmin(employee_panel)
    task_reader = _login_employee(
        employee_panel,
        super_jar,
        username="task.reader",
        permissions=frozenset({"tasks.view"}),
    )
    queue_reader = _login_employee(
        employee_panel,
        super_jar,
        username="queue.reader",
        permissions=frozenset({"queue.view"}),
    )

    status, _url, body, _headers = _request(
        employee_panel.base, "/aufgaben", jar=task_reader
    )
    assert status == 200
    assert "Aufgaben" in body

    status, _url, body, _headers = _request(
        employee_panel.base, "/aufgaben", jar=queue_reader
    )
    assert status == 403
    assert "Ihre Berechtigung reicht" in body


def test_manual_tasks_render_created_data_escaped(
    employee_panel: PanelHarness,
) -> None:
    super_jar = _ready_superadmin(employee_panel)
    jar = _login_employee(
        employee_panel,
        super_jar,
        username="task.creator",
        permissions=frozenset({"tasks.view", "tasks.create", "tasks.complete"}),
    )

    status, _url, _body, _headers = _request(
        employee_panel.base,
        "/aufgaben/new",
        method="POST",
        data={
            "_csrf_token": _csrf(jar),
            "title": "<script>alert(1)</script>",
            "description": "Rechnung vorbereiten",
            "due_date": "2026-08-27",
        },
        jar=jar,
    )
    assert status == 303

    status, _url, body, _headers = _request(employee_panel.base, "/aufgaben", jar=jar)
    assert status == 200
    assert "Manuell" in body
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body
    assert "<script>alert(1)</script>" not in body
    assert "Rechnung vorbereiten" in body
    assert "27.08.2026" in body
    assert 'action="/aufgaben/inquiry:' not in body


def test_create_permission_controls_form_and_post(
    employee_panel: PanelHarness,
) -> None:
    super_jar = _ready_superadmin(employee_panel)
    viewer = _login_employee(
        employee_panel,
        super_jar,
        username="task.no.create",
        permissions=frozenset({"tasks.view"}),
    )

    status, _url, body, _headers = _request(
        employee_panel.base, "/aufgaben", jar=viewer
    )
    assert status == 200
    assert "Aufgabe anlegen" not in body

    status, _url, body, _headers = _request(
        employee_panel.base,
        "/aufgaben/new",
        method="POST",
        data={"_csrf_token": _csrf(viewer), "title": "Nicht erlaubt"},
        jar=viewer,
    )
    assert status == 403
    assert "Ihre Berechtigung reicht" in body


def test_assignment_requires_tasks_assign_server_side(
    employee_panel: PanelHarness,
) -> None:
    super_jar = _ready_superadmin(employee_panel)
    assignee_id = _create_employee(
        employee_panel,
        super_jar,
        username="task.assignee",
        password="TaskTemp1!",
        role="USER",
        permissions=frozenset({"tasks.view"}),
    )
    assigner = _login_employee(
        employee_panel,
        super_jar,
        username="task.assigner",
        permissions=frozenset({"tasks.view", "tasks.create", "tasks.assign"}),
    )
    creator = _login_employee(
        employee_panel,
        super_jar,
        username="task.no.assign",
        permissions=frozenset({"tasks.view", "tasks.create"}),
    )

    status, _url, body, _headers = _request(
        employee_panel.base, "/aufgaben", jar=assigner
    )
    assert status == 200
    assert 'name="assigned_to_employee_id"' in body
    assert "task.assignee" in body

    status, _url, body, _headers = _request(
        employee_panel.base, "/aufgaben", jar=creator
    )
    assert status == 200
    assert 'name="assigned_to_employee_id"' not in body

    status, _url, body, _headers = _request(
        employee_panel.base,
        "/aufgaben/new",
        method="POST",
        data={
            "_csrf_token": _csrf(creator),
            "title": "Forged assignment",
            "assigned_to_employee_id": assignee_id,
        },
        jar=creator,
    )
    assert status == 403
    assert "Ihre Berechtigung reicht" in body

    status, _url, _body, _headers = _request(
        employee_panel.base,
        "/aufgaben/new",
        method="POST",
        data={
            "_csrf_token": _csrf(assigner),
            "title": "Mit Zuweisung",
            "assigned_to_employee_id": assignee_id,
        },
        jar=assigner,
    )
    assert status == 303
    status, _url, body, _headers = _request(
        employee_panel.base, "/aufgaben", jar=assigner
    )
    assert status == 200
    assert "Mit Zuweisung" in body
    assert "task.assignee" in body


def test_complete_permission_controls_button_and_post(
    employee_panel: PanelHarness,
) -> None:
    super_jar = _ready_superadmin(employee_panel)
    completer = _login_employee(
        employee_panel,
        super_jar,
        username="task.completer",
        permissions=frozenset({"tasks.view", "tasks.create", "tasks.complete"}),
    )
    viewer = _login_employee(
        employee_panel,
        super_jar,
        username="task.no.complete",
        permissions=frozenset({"tasks.view"}),
    )
    status, _url, _body, _headers = _request(
        employee_panel.base,
        "/aufgaben/new",
        method="POST",
        data={"_csrf_token": _csrf(completer), "title": "Abschliessen"},
        jar=completer,
    )
    assert status == 303

    status, _url, body, _headers = _request(
        employee_panel.base, "/aufgaben", jar=viewer
    )
    assert status == 200
    assert "Abschliessen" in body
    assert "Erledigt" not in body

    status, _url, body, _headers = _request(
        employee_panel.base, "/aufgaben", jar=completer
    )
    assert status == 200
    assert "Erledigt" in body
    task_match = re.search(r'action="/aufgaben/([0-9a-f-]{36})/complete"', body)
    assert task_match is not None
    task_id = task_match.group(1)
    status, _url, body, _headers = _request(
        employee_panel.base,
        f"/aufgaben/{task_id}/complete",
        method="POST",
        data={"_csrf_token": _csrf(viewer)},
        jar=viewer,
    )
    assert status == 403
    assert "Ihre Berechtigung reicht" in body

    status, _url, _body, _headers = _request(
        employee_panel.base,
        f"/aufgaben/{task_id}/complete",
        method="POST",
        data={"_csrf_token": _csrf(completer)},
        jar=completer,
    )
    assert status == 303
    status, _url, body, _headers = _request(
        employee_panel.base, "/aufgaben", jar=completer
    )
    assert status == 200
    assert "Abschliessen" not in body


def test_create_requires_valid_csrf_and_does_not_mutate_on_failure(
    employee_panel: PanelHarness,
) -> None:
    super_jar = _ready_superadmin(employee_panel)
    jar = _login_employee(
        employee_panel,
        super_jar,
        username="task.csrf",
        permissions=frozenset({"tasks.view", "tasks.create"}),
    )

    status, _url, body, _headers = _request(
        employee_panel.base,
        "/aufgaben/new",
        method="POST",
        data={"title": "No CSRF"},
        jar=jar,
    )
    assert status == 403
    assert "CSRF" in body

    status, _url, body, _headers = _request(employee_panel.base, "/aufgaben", jar=jar)
    assert status == 200
    assert "No CSRF" not in body


class _RemoteStub:
    def __init__(self) -> None:
        self.inquiry_service = object()
        self.order_service = object()
        self.core = object()
        self.payment_reminder_service = object()
        self.confirmation_document_service = object()
        self.confirmation_outbound_service = object()
        self.catalog_dish_write_service = object()
        self.seen_tokens: list[str] = []
        self.created_token: str | None = None
        self.completed_token: str | None = None
        self._form: dict[str, str] = {}

    def begin_request(self, form=None) -> None:
        self._form = dict(form or {})

    def new_page_command_id(self) -> str:
        return "44444444-4444-4444-8444-444444444444"

    def form_value(self, key: str) -> str | None:
        return self._form.get(key)

    def list_tasks(self) -> dict[str, object]:
        return {
            "tasks": [
                {
                    "task_id": "inquiry:abc:verify",
                    "category": "verify",
                    "title": "System Aufgabe",
                    "subtitle": "aus Projektion",
                    "entity_type": "inquiry",
                    "entity_id": "abc",
                    "action_label": "Anfrage öffnen",
                    "action_href": "/inquiry/abc",
                    "due_at": None,
                    "urgency": "normal",
                    "opened_at": "2026-08-01T08:00:00+00:00",
                }
            ]
        }

    def list_manual_tasks(self, *, employee_session_token: str, **_kwargs):
        self.seen_tokens.append(employee_session_token)
        return [
            ManualTask(
                task_id="11111111-1111-4111-8111-111111111111",
                title="Remote Aufgabe",
                description="",
                due_at=None,
                created_at=datetime(2026, 8, 1, 8, 0, tzinfo=UTC),
                completed_at=None,
                created_by_employee_id="22222222-2222-4222-8222-222222222222",
                assigned_to_employee_id=None,
                subject_type="NONE",
                subject_id=None,
            )
        ]

    def list_manual_task_subjects(self, *, employee_session_token: str):
        return []

    def create_manual_task(self, *, employee_session_token: str, **_kwargs):
        self.created_token = employee_session_token
        return self.list_manual_tasks(employee_session_token=employee_session_token)[0]

    def complete_manual_task(
        self, _task_id: str, *, employee_session_token: str, **_kwargs
    ):
        self.completed_token = employee_session_token
        return self.list_manual_tasks(employee_session_token=employee_session_token)[0]


def test_remote_manual_tasks_use_employee_session_token() -> None:
    remote = _RemoteStub()
    panel = OfficePanel(
        InMemoryInquiryRepository(),
        InMemoryOrderRepository(),
        remote=remote,  # type: ignore[arg-type]
    )
    context = OfficePageContext(
        csrf_token="csrf-token",
        employee_account_id="22222222-2222-4222-8222-222222222222",
        employee_effective_permissions=frozenset(
            {"tasks.view", "tasks.create", "tasks.complete"}
        ),
    )

    html = panel.render_aufgaben(
        context=context, employee_session_token="employee-session-token"
    )
    assert "Remote Aufgabe" in html
    assert "System Aufgabe" in html
    assert "Manuell" in html
    assert "System" in html
    assert 'href="/inquiry/abc"' in html
    assert 'action="/aufgaben/inquiry:abc:verify/complete"' not in html
    assert remote.seen_tokens == ["employee-session-token"]

    panel.begin_request({"_command_id": "cmd-1"})
    panel.create_manual_task(
        {"title": "Remote neu", "_command_id": "cmd-1"},
        created_by_employee_id=context.employee_account_id,
        employee_session_token="employee-session-token",
    )
    assert remote.created_token == "employee-session-token"

    panel.begin_request({"_command_id": "cmd-2"})
    panel.complete_manual_task(
        "11111111-1111-4111-8111-111111111111",
        employee_session_token="employee-session-token",
    )
    assert remote.completed_token == "employee-session-token"
