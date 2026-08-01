from __future__ import annotations

import json
import queue
import threading
import urllib.error
import urllib.request
from datetime import UTC, datetime
from http.server import HTTPServer
from pathlib import Path

import pytest

from catering_system.repositories.sqlite_employee_auth_repository import (
    SQLiteEmployeeAuthRepository,
)
from catering_system.services.employee_auth_service import EmployeeAuthService


def _seed(db: Path) -> None:
    repo = SQLiteEmployeeAuthRepository(db)
    service = EmployeeAuthService(
        repo,
        now=lambda: datetime(2026, 8, 1, 10, 0, tzinfo=UTC),
    )
    service.bootstrap_superadmin(
        username="super.admin",
        display_name="Super Admin",
        password="TempPassw0rd!",
        metadata={"seed": "accounts-api"},
    )
    repo.close()


def _start_server(db: Path) -> tuple[HTTPServer, threading.Thread, str]:
    ready: queue.Queue[HTTPServer] = queue.Queue()

    def run() -> None:
        from catering_system.ui.employee_auth_api import create_employee_auth_server

        server = create_employee_auth_server(
            db,
            host="127.0.0.1",
            port=0,
            secure_cookie=False,
        )
        ready.put(server)
        server.serve_forever()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    server = ready.get(timeout=5)
    host, port = server.server_address[:2]
    return server, thread, f"http://{host}:{port}"


@pytest.fixture()
def auth_api(tmp_path: Path):
    db = tmp_path / "core.db"
    _seed(db)
    server, thread, base = _start_server(db)
    yield base
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def _request(
    url: str,
    *,
    method: str = "GET",
    body: dict[str, object] | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, object], dict[str, str]]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    if body is not None and "Content-Type" not in (headers or {}):
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request) as response:
            raw = response.read()
            parsed = json.loads(raw) if raw else {}
            return response.status, parsed, dict(response.headers)
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        parsed = json.loads(raw) if raw else {}
        return exc.code, parsed, dict(exc.headers)


def _login_ready(base: str, *, username: str, password: str) -> tuple[str, str]:
    status, body, headers = _request(
        f"{base}/auth/login",
        method="POST",
        body={"username": username, "password": password},
    )
    assert status == 200
    cookie = headers["Set-Cookie"]
    csrf = str(body["csrf_token"])
    status, _body, _headers = _request(
        f"{base}/auth/password/change",
        method="POST",
        headers={"Cookie": cookie, "X-CSRF-Token": csrf},
        body={"current_password": password, "new_password": "ChangedTemp1!"},
    )
    assert status == 204
    status, body, headers = _request(
        f"{base}/auth/login",
        method="POST",
        body={"username": username, "password": "ChangedTemp1!"},
    )
    assert status == 200
    return headers["Set-Cookie"], str(body["csrf_token"])


@pytest.fixture()
def superadmin_session(auth_api: str):
    return _login_ready(auth_api, username="super.admin", password="TempPassw0rd!")


def test_unauthenticated_accounts_request_returns_401(auth_api: str) -> None:
    status, body, _headers = _request(f"{auth_api}/auth/accounts")
    assert status == 401
    assert body["error"] == "unauthorized"


def test_superadmin_can_list_and_create_accounts(
    auth_api: str, superadmin_session: tuple[str, str]
) -> None:
    cookie, csrf = superadmin_session
    status, body, _headers = _request(
        f"{auth_api}/auth/accounts",
        headers={"Cookie": cookie},
    )
    assert status == 200
    assert body["accounts"]
    status, body, _headers = _request(
        f"{auth_api}/auth/accounts",
        method="POST",
        headers={"Cookie": cookie, "X-CSRF-Token": csrf},
        body={
            "username": "worker.api",
            "display_name": "Worker API",
            "role": "USER",
            "temporary_password": "WorkerTemp1!",
        },
    )
    assert status == 201
    assert body["account"]["username"] == "worker.api"


def test_unknown_json_key_rejected(
    auth_api: str, superadmin_session: tuple[str, str]
) -> None:
    cookie, csrf = superadmin_session
    status, body, _headers = _request(
        f"{auth_api}/auth/accounts",
        method="POST",
        headers={"Cookie": cookie, "X-CSRF-Token": csrf},
        body={
            "username": "worker.unknown",
            "display_name": "Worker Unknown",
            "role": "USER",
            "temporary_password": "WorkerTemp1!",
            "unexpected": True,
        },
    )
    assert status == 400
    assert body["error"] == "invalid_request"


def test_csrf_missing_and_cross_session_return_403(
    auth_api: str, superadmin_session: tuple[str, str]
) -> None:
    cookie, _csrf = superadmin_session
    status, body, _headers = _request(
        f"{auth_api}/auth/accounts",
        method="POST",
        headers={"Cookie": cookie},
        body={
            "username": "worker.csrf",
            "display_name": "Worker CSRF",
            "role": "USER",
            "temporary_password": "WorkerTemp1!",
        },
    )
    assert status == 403
    assert body["error"] == "forbidden"

    _status, _body, headers_b = _request(
        f"{auth_api}/auth/login",
        method="POST",
        body={"username": "super.admin", "password": "ChangedTemp1!"},
    )
    cookie_b = headers_b["Set-Cookie"]
    csrf_a = superadmin_session[1]
    status, body, _headers = _request(
        f"{auth_api}/auth/accounts",
        method="POST",
        headers={"Cookie": cookie_b, "X-CSRF-Token": csrf_a},
        body={
            "username": "worker.cross",
            "display_name": "Worker Cross",
            "role": "USER",
            "temporary_password": "WorkerTemp1!",
        },
    )
    assert status == 403
    assert body["error"] == "forbidden"


def test_account_detail_permissions_role_and_reset_password_flow(
    auth_api: str, superadmin_session: tuple[str, str]
) -> None:
    cookie, csrf = superadmin_session
    status, created, _headers = _request(
        f"{auth_api}/auth/accounts",
        method="POST",
        headers={"Cookie": cookie, "X-CSRF-Token": csrf},
        body={
            "username": "worker.flow",
            "display_name": "Worker Flow",
            "role": "USER",
            "temporary_password": "WorkerTemp1!",
            "permissions": ["offers.prepare", "offers.view"],
        },
    )
    assert status == 201
    account_id = str(created["account"]["id"])
    status, body, _headers = _request(
        f"{auth_api}/auth/accounts/{account_id}",
        headers={"Cookie": cookie},
    )
    assert status == 200
    assert "offers.prepare" in body["account"]["effective_permissions"]

    status, body, _headers = _request(
        f"{auth_api}/auth/accounts/{account_id}",
        method="PATCH",
        headers={"Cookie": cookie, "X-CSRF-Token": csrf},
        body={"display_name": "Worker Flow Updated"},
    )
    assert status == 200
    assert body["account"]["display_name"] == "Worker Flow Updated"

    status, body, _headers = _request(
        f"{auth_api}/auth/accounts/{account_id}/role",
        method="POST",
        headers={"Cookie": cookie, "X-CSRF-Token": csrf},
        body={"role": "VIEWER"},
    )
    assert status == 200
    assert body["account"]["role"] == "VIEWER"
    assert body["account"]["effective_permissions"] == ["offers.view"]

    status, body, _headers = _request(
        f"{auth_api}/auth/accounts/{account_id}/permissions",
        method="PUT",
        headers={"Cookie": cookie, "X-CSRF-Token": csrf},
        body={"permissions": ["inquiries.view", "offers.view"]},
    )
    assert status == 200

    status, body, _headers = _request(
        f"{auth_api}/auth/accounts/{account_id}/reset-password",
        method="POST",
        headers={"Cookie": cookie, "X-CSRF-Token": csrf},
        body={},
    )
    assert status == 200
    assert body["account"]["must_change_password"] is True
    assert "temporary_password" in body
    assert "WorkerTemp1!" not in json.dumps(body)

    status, body, _headers = _request(
        f"{auth_api}/auth/accounts/{account_id}/audit-events",
        headers={"Cookie": cookie},
    )
    assert status == 200
    assert body["events"]


def test_admin_cannot_create_admin_via_api(
    auth_api: str, superadmin_session: tuple[str, str]
) -> None:
    cookie, csrf = superadmin_session
    status, _body, _headers = _request(
        f"{auth_api}/auth/accounts",
        method="POST",
        headers={"Cookie": cookie, "X-CSRF-Token": csrf},
        body={
            "username": "team.admin",
            "display_name": "Team Admin",
            "role": "ADMIN",
            "temporary_password": "AdminTemp1!",
        },
    )
    assert status == 201
    admin_cookie, admin_csrf = _login_ready(
        auth_api, username="team.admin", password="AdminTemp1!"
    )
    status, body, _headers = _request(
        f"{auth_api}/auth/accounts",
        method="POST",
        headers={"Cookie": admin_cookie, "X-CSRF-Token": admin_csrf},
        body={
            "username": "blocked.admin",
            "display_name": "Blocked Admin",
            "role": "ADMIN",
            "temporary_password": "BlockedTemp1!",
        },
    )
    assert status == 403
    assert body["error"] == "forbidden"


def test_last_active_superadmin_conflict_via_api(
    auth_api: str, superadmin_session: tuple[str, str]
) -> None:
    cookie, csrf = superadmin_session
    status, me, _headers = _request(
        f"{auth_api}/auth/me",
        headers={"Cookie": cookie},
    )
    assert status == 200
    account_id = str(me["account"]["id"])
    status, body, _headers = _request(
        f"{auth_api}/auth/accounts/{account_id}/deactivate",
        method="POST",
        headers={"Cookie": cookie, "X-CSRF-Token": csrf},
        body={},
    )
    assert status == 409
    assert body["error"] == "last_active_superadmin"
