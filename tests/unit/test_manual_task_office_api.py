from __future__ import annotations

import json
import queue
import threading
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime, timedelta
from http.server import HTTPServer
from pathlib import Path

import pytest

from catering_system.domain.employee_auth import (
    role_ceiling,
    role_default_grants,
    validate_permission_code,
)
from catering_system.repositories.sqlite_employee_auth_repository import (
    SQLiteEmployeeAuthRepository,
)
from catering_system.services.employee_auth_service import EmployeeAuthService
from catering_system.ui.remote_core_client import RemoteCoreClient, RemoteCoreError
from tests.helpers.offer_pdf_static_content import fake_offer_pdf_static_content

_TOKEN = "test-office-api-token"
_AUTH = {"Authorization": f"Bearer {_TOKEN}"}
_NOW = datetime(2026, 8, 9, 8, 0, tzinfo=UTC)
_DUE = _NOW + timedelta(days=1)


def _start_api_server(db: Path) -> tuple[HTTPServer, threading.Thread, str]:
    ready: queue.Queue[HTTPServer] = queue.Queue()

    def run() -> None:
        from catering_system.ui.office_api import create_office_api_server

        server = create_office_api_server(
            str(db),
            _TOKEN,
            "127.0.0.1",
            0,
            offer_pdf_static_content=fake_offer_pdf_static_content(),
            employee_auth_now=lambda: _NOW,
        )
        ready.put(server)
        server.serve_forever()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    server = ready.get(timeout=5)
    host, port = server.server_address[:2]
    return server, thread, f"http://{host}:{port}"


def _seed_auth(db: Path) -> dict[str, str]:
    repo = SQLiteEmployeeAuthRepository(db)
    service = EmployeeAuthService(repo, now=lambda: _NOW)
    admin = service.bootstrap_superadmin(
        username="manual.admin",
        display_name="Manual Admin",
        password="TempPassw0rd!",
    )
    initial = service.authenticate(username="manual.admin", password="TempPassw0rd!")
    service.change_password(
        service.authenticate_session(initial.session_token),
        current_password="TempPassw0rd!",
        new_password="ChangedPassw0rd!",
    )
    admin_session = service.authenticate(
        username="manual.admin", password="ChangedPassw0rd!"
    ).session_token
    admin_actor = service.authenticate_session(admin_session)
    worker = service.create_account(
        admin_actor,
        username="manual.worker",
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
    viewer = service.create_account(
        admin_actor,
        username="manual.viewer",
        display_name="Manual Viewer",
        password="ViewerPassw0rd!",
        role="VIEWER",
        explicit_permissions={"tasks.view"},
        must_change_password=False,
    )
    assignee = service.create_account(
        admin_actor,
        username="manual.assignee",
        display_name="Manual Assignee",
        password="AssignPassw0rd!",
        role="USER",
        explicit_permissions={"tasks.view"},
        must_change_password=False,
    )
    creator = service.create_account(
        admin_actor,
        username="manual.creator",
        display_name="Manual Creator",
        password="CreatePassw0rd!",
        role="USER",
        explicit_permissions={"tasks.view", "tasks.create", "tasks.complete"},
        must_change_password=False,
    )
    no_view = service.create_account(
        admin_actor,
        username="manual.no.view",
        display_name="Manual No View",
        password="NoViewPassw0rd!",
        role="USER",
        explicit_permissions={"tasks.create"},
        must_change_password=False,
    )
    queue_only = service.create_account(
        admin_actor,
        username="manual.queue.only",
        display_name="Manual Queue Only",
        password="QueuePassw0rd!",
        role="USER",
        explicit_permissions={"queue.view"},
        must_change_password=False,
    )
    worker_login = service.authenticate(
        username="manual.worker", password="WorkerPassw0rd!"
    )
    viewer_login = service.authenticate(
        username="manual.viewer", password="ViewerPassw0rd!"
    )
    creator_login = service.authenticate(
        username="manual.creator", password="CreatePassw0rd!"
    )
    no_view_login = service.authenticate(
        username="manual.no.view", password="NoViewPassw0rd!"
    )
    queue_only_login = service.authenticate(
        username="manual.queue.only", password="QueuePassw0rd!"
    )
    repo.close()
    return {
        "admin_id": admin.id,
        "worker_id": worker.id,
        "worker_session": worker_login.session_token,
        "viewer_id": viewer.id,
        "viewer_session": viewer_login.session_token,
        "assignee_id": assignee.id,
        "creator_id": creator.id,
        "creator_session": creator_login.session_token,
        "no_view_id": no_view.id,
        "no_view_session": no_view_login.session_token,
        "queue_only_id": queue_only.id,
        "queue_only_session": queue_only_login.session_token,
    }


@pytest.fixture()
def manual_task_api(tmp_path: Path):
    db = tmp_path / "core.db"
    ids = _seed_auth(db)
    server, thread, base = _start_api_server(db)
    try:
        yield base, ids
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert thread.is_alive() is False


def _headers(session_token: str) -> dict[str, str]:
    return {**_AUTH, "X-Employee-Session": session_token}


def test_manual_task_permissions_are_registered_in_role_model() -> None:
    for permission in {
        "tasks.view",
        "tasks.create",
        "tasks.complete",
        "tasks.assign",
    }:
        assert validate_permission_code(permission) == permission
        assert permission in role_ceiling("ADMIN")
        assert permission in role_ceiling("USER")
    assert "tasks.view" in role_ceiling("VIEWER")
    assert "tasks.create" not in role_ceiling("VIEWER")
    assert "tasks.assign" in role_default_grants("ADMIN")
    assert "tasks.assign" not in role_default_grants("USER")


def _get(url: str, headers: dict[str, str]) -> tuple[int, dict[str, object]]:
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode() or "{}")


def _post(
    url: str,
    *,
    args: dict[str, object] | None = None,
    headers: dict[str, str],
    command_id: str | None = None,
) -> tuple[int, dict[str, object]]:
    body = json.dumps(
        {
            "command_id": command_id or str(uuid.uuid4()),
            "expect": {},
            "args": args or {},
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={**headers, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode() or "{}")


def test_manual_task_api_create_list_complete_with_assignee(manual_task_api) -> None:
    base, ids = manual_task_api
    headers = _headers(ids["worker_session"])

    status, created = _post(
        f"{base}/office/v1/manual-tasks",
        headers=headers,
        args={
            "title": "Rechnung vorbereiten",
            "description": "Barzahlung vor Ort",
            "due_at": _DUE.isoformat(),
            "assigned_to_employee_id": ids["assignee_id"],
            "subject_type": "NONE",
            "subject_id": None,
        },
    )

    assert status == 201
    task = created["manual_task"]
    assert isinstance(task, dict)
    assert task["title"] == "Rechnung vorbereiten"
    assert task["created_by_employee_id"] == ids["worker_id"]
    assert task["assigned_to_employee_id"] == ids["assignee_id"]
    assert task["status"] == "OPEN"

    status, listed = _get(f"{base}/office/v1/manual-tasks", headers)
    assert status == 200
    assert listed["manual_tasks"] == [task]

    task_id = str(task["task_id"])
    status, completed = _post(
        f"{base}/office/v1/manual-tasks/{task_id}/complete",
        headers=headers,
    )
    assert status == 200
    completed_task = completed["manual_task"]
    assert isinstance(completed_task, dict)
    assert completed_task["status"] == "DONE"
    assert completed_task["completed_at"] is not None

    status, listed_after = _get(f"{base}/office/v1/manual-tasks", headers)
    assert status == 200
    assert listed_after["manual_tasks"] == []


def test_manual_task_api_requires_employee_permissions(manual_task_api) -> None:
    base, ids = manual_task_api

    status, body = _get(f"{base}/office/v1/manual-tasks", _AUTH)
    assert (status, body["error"]) == (401, "unauthorized")

    status, body = _post(
        f"{base}/office/v1/manual-tasks",
        headers=_headers(ids["viewer_session"]),
        args={"title": "Nicht erlaubt"},
    )
    assert (status, body["error"]) == (403, "forbidden")

    status, body = _post(
        f"{base}/office/v1/manual-tasks",
        headers=_headers(ids["viewer_session"]),
        args={
            "title": "Nicht erlaubt",
            "assigned_to_employee_id": ids["assignee_id"],
        },
    )
    assert (status, body["error"]) == (403, "forbidden")


def test_manual_task_create_without_assign_permission_boundaries(
    manual_task_api,
) -> None:
    base, ids = manual_task_api
    headers = _headers(ids["creator_session"])

    status, created = _post(
        f"{base}/office/v1/manual-tasks",
        headers=headers,
        args={"title": "Ohne Zuweisung"},
    )
    assert status == 201
    task = created["manual_task"]
    assert isinstance(task, dict)
    assert task["assigned_to_employee_id"] is None

    status, body = _post(
        f"{base}/office/v1/manual-tasks",
        headers=headers,
        args={
            "title": "Eigene Zuweisung",
            "assigned_to_employee_id": ids["creator_id"],
        },
    )
    assert (status, body["error"]) == (403, "forbidden")

    status, body = _post(
        f"{base}/office/v1/manual-tasks",
        headers=headers,
        args={
            "title": "Fremde Zuweisung",
            "assigned_to_employee_id": ids["assignee_id"],
        },
    )
    assert (status, body["error"]) == (403, "forbidden")


def test_manual_task_list_requires_tasks_view_not_queue_view(manual_task_api) -> None:
    base, ids = manual_task_api

    status, _body = _get(
        f"{base}/office/v1/manual-tasks",
        _headers(ids["viewer_session"]),
    )
    assert status == 200

    status, body = _get(
        f"{base}/office/v1/manual-tasks",
        _headers(ids["no_view_session"]),
    )
    assert (status, body["error"]) == (403, "forbidden")

    status, body = _get(
        f"{base}/office/v1/manual-tasks",
        _headers(ids["queue_only_session"]),
    )
    assert (status, body["error"]) == (403, "forbidden")


def test_remote_core_client_manual_task_parity(manual_task_api) -> None:
    base, ids = manual_task_api
    client = RemoteCoreClient(base, _TOKEN)

    created = client.create_manual_task(
        employee_session_token=ids["worker_session"],
        title="Kunden anrufen",
        description=None,
        due_at=_DUE,
    )
    listed = client.list_manual_tasks(employee_session_token=ids["worker_session"])
    completed = client.complete_manual_task(
        created.task_id,
        employee_session_token=ids["worker_session"],
    )

    assert listed == [created]
    assert completed.task_id == created.task_id
    assert completed.status == "DONE"
    with pytest.raises(RemoteCoreError) as exc:
        client.create_manual_task(
            employee_session_token=ids["viewer_session"],
            title="Nicht erlaubt",
        )
    assert (exc.value.status, exc.value.code) == (403, "forbidden")


def test_remote_core_client_preserves_manual_task_authorization(
    manual_task_api,
) -> None:
    base, ids = manual_task_api
    client = RemoteCoreClient(base, _TOKEN)

    assert client.list_manual_tasks(employee_session_token=ids["viewer_session"]) == []
    with pytest.raises(RemoteCoreError) as exc:
        client.list_manual_tasks(employee_session_token=ids["queue_only_session"])
    assert (exc.value.status, exc.value.code) == (403, "forbidden")

    client.create_manual_task(
        employee_session_token=ids["creator_session"],
        title="Ohne Zuweisung",
    )
    with pytest.raises(RemoteCoreError) as exc:
        client.create_manual_task(
            employee_session_token=ids["creator_session"],
            title="Fremde Zuweisung",
            assigned_to_employee_id=ids["assignee_id"],
        )
    assert (exc.value.status, exc.value.code) == (403, "forbidden")
