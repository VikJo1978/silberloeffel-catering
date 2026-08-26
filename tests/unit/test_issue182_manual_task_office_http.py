from __future__ import annotations

import http.cookiejar
import queue
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import pytest

from catering_system.repositories.employee_auth_runtime import (
    ManagedEmployeeAuthRuntime,
    open_managed_employee_auth_runtime,
)
from catering_system.repositories.in_memory_inquiry_repository import (
    InMemoryInquiryRepository,
)
from catering_system.repositories.in_memory_order_repository import (
    InMemoryOrderRepository,
)
from catering_system.ui.office_panel import create_office_panel_server

_NOW = datetime(2026, 8, 26, 8, 0, tzinfo=UTC)
_Ready = tuple[object, ManagedEmployeeAuthRuntime, str, str]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _cookie_value(jar: http.cookiejar.CookieJar, name: str) -> str:
    for cookie in jar:
        if cookie.name == name:
            return cookie.value
    raise AssertionError(f"missing cookie {name}")


def _request(
    base: str,
    path: str,
    *,
    method: str = "GET",
    data: dict[str, str] | None = None,
    jar: http.cookiejar.CookieJar | None = None,
) -> tuple[int, str, object]:
    cookie_jar = jar if jar is not None else http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(
        _NoRedirect,
        urllib.request.HTTPCookieProcessor(cookie_jar),
    )
    payload = urllib.parse.urlencode(data).encode() if data is not None else None
    request = urllib.request.Request(f"{base}{path}", data=payload, method=method)
    try:
        with opener.open(request) as response:
            return response.status, response.read().decode("utf-8"), response.headers
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8"), exc.headers


class _Panel:
    def __init__(
        self,
        *,
        base: str,
        server: object,
        thread: threading.Thread,
        runtime: ManagedEmployeeAuthRuntime,
        worker_id: str,
        assignee_id: str,
    ) -> None:
        self.base = base
        self.server = server
        self.thread = thread
        self.runtime = runtime
        self.worker_id = worker_id
        self.assignee_id = assignee_id


def _start_panel(tmp_path: Path) -> _Panel:
    db = tmp_path / "core.db"
    ready: queue.Queue[_Ready] = queue.Queue()

    def run() -> None:
        runtime = open_managed_employee_auth_runtime(db, now=lambda: _NOW)
        runtime.service.bootstrap_superadmin(
            username="issue182.admin",
            display_name="Issue 182 Admin",
            password="TempPassw0rd!",
        )
        initial = runtime.service.authenticate(
            username="issue182.admin", password="TempPassw0rd!"
        )
        actor = runtime.service.authenticate_session(initial.session_token)
        runtime.service.change_password(
            actor,
            current_password="TempPassw0rd!",
            new_password="ChangedPassw0rd!",
        )
        admin_login = runtime.service.authenticate(
            username="issue182.admin", password="ChangedPassw0rd!"
        )
        actor = runtime.service.authenticate_session(admin_login.session_token)
        worker = runtime.service.create_account(
            actor,
            username="issue182.worker",
            display_name="Manual Worker",
            password="WorkerPassw0rd!",
            role="USER",
            explicit_permissions={
                "tasks.view",
                "tasks.create",
                "tasks.complete",
                "tasks.assign",
            },
            must_change_password=False,
        )
        assignee = runtime.service.create_account(
            actor,
            username="issue182.assignee",
            display_name="Manual Assignee",
            password="AssigneePassw0rd!",
            role="USER",
            explicit_permissions={"tasks.view"},
            must_change_password=False,
        )
        server = create_office_panel_server(
            InMemoryInquiryRepository(),
            InMemoryOrderRepository(),
            "shared-office-password",
            host="127.0.0.1",
            port=0,
            auth_mode="employee",
            auth_service=runtime.service,
            secure_cookie=False,
            ui_version="v2",
        )
        ready.put((server, runtime, worker.id, assignee.id))
        server.serve_forever()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    server, runtime, worker_id, assignee_id = ready.get(timeout=5)
    host, port = server.server_address[:2]
    return _Panel(
        base=f"http://{host}:{port}",
        server=server,
        thread=thread,
        runtime=runtime,
        worker_id=worker_id,
        assignee_id=assignee_id,
    )


@pytest.fixture()
def issue182_panel(tmp_path: Path):
    panel = _start_panel(tmp_path)
    try:
        yield panel
    finally:
        panel.server.shutdown()
        panel.server.server_close()
        panel.thread.join(timeout=5)
        panel.runtime.close()
        assert panel.thread.is_alive() is False


def _login(panel: _Panel, username: str, password: str) -> http.cookiejar.CookieJar:
    jar = http.cookiejar.CookieJar()
    status, _body, _headers = _request(
        panel.base,
        "/login",
        method="POST",
        data={"username": username, "password": password, "next": "/aufgaben"},
        jar=jar,
    )
    assert status == 303
    return jar


def test_manual_task_office_http_flow(issue182_panel: _Panel) -> None:
    jar = _login(issue182_panel, "issue182.worker", "WorkerPassw0rd!")
    csrf = _cookie_value(jar, "sl_employee_csrf")

    status, body, _headers = _request(issue182_panel.base, "/aufgaben", jar=jar)
    assert status == 200
    assert "Neue Aufgabe" in body
    assert "Automatisch abgeleitete Aufgaben" not in body

    status, _body, headers = _request(
        issue182_panel.base,
        "/aufgaben/manual",
        method="POST",
        data={
            "_csrf_token": csrf,
            "title": "Kunden anrufen",
            "description": "Termin bestätigen",
            "due_at": "2026-08-27T10:30",
            "assigned_to_employee_id": issue182_panel.assignee_id,
            "subject_type": "NONE",
            "subject_id": "",
        },
        jar=jar,
    )
    assert status == 303
    assert headers["Location"] == "/aufgaben?msg=created"

    status, body, _headers = _request(issue182_panel.base, "/aufgaben", jar=jar)
    assert status == 200
    assert "Kunden anrufen" in body
    assert "Termin bestätigen" in body
    assert "Manual Assignee" in body

    row = issue182_panel.runtime.repository._conn.execute(
        "SELECT task_id, status, assigned_to_employee_id FROM manual_tasks"
    ).fetchone()
    assert row is not None
    task_id = str(row[0])
    assert row[1] == "OPEN"
    assert row[2] == issue182_panel.assignee_id

    status, _body, headers = _request(
        issue182_panel.base,
        f"/aufgaben/manual/{urllib.parse.quote(task_id)}/complete",
        method="POST",
        data={"_csrf_token": csrf},
        jar=jar,
    )
    assert status == 303
    assert headers["Location"] == "/aufgaben?msg=completed"

    status, body, _headers = _request(issue182_panel.base, "/aufgaben", jar=jar)
    assert status == 200
    assert "Kunden anrufen" not in body
    completed = issue182_panel.runtime.repository._conn.execute(
        "SELECT status, completed_at FROM manual_tasks WHERE task_id = ?",
        (task_id,),
    ).fetchone()
    assert completed is not None
    assert completed[0] == "DONE"
    assert completed[1] is not None


def test_manual_task_office_http_viewer_read_only(issue182_panel: _Panel) -> None:
    worker_jar = _login(issue182_panel, "issue182.worker", "WorkerPassw0rd!")
    worker_csrf = _cookie_value(worker_jar, "sl_employee_csrf")
    status, _body, _headers = _request(
        issue182_panel.base,
        "/aufgaben/manual",
        method="POST",
        data={
            "_csrf_token": worker_csrf,
            "title": "Nur ansehen",
            "due_at": "",
            "assigned_to_employee_id": "",
            "subject_type": "NONE",
            "subject_id": "",
        },
        jar=worker_jar,
    )
    assert status == 303

    viewer_jar = _login(issue182_panel, "issue182.assignee", "AssigneePassw0rd!")
    status, body, _headers = _request(issue182_panel.base, "/aufgaben", jar=viewer_jar)
    assert status == 200
    assert "Nur ansehen" in body
    assert "Neue Aufgabe" not in body
    assert "/complete" not in body
    assert "Automatisch abgeleitete Aufgaben" not in body
