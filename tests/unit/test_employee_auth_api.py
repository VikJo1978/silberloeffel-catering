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


def _seed_auth(db: Path) -> None:
    repo = SQLiteEmployeeAuthRepository(db)
    service = EmployeeAuthService(
        repo,
        now=lambda: datetime(2026, 8, 1, 10, 0, tzinfo=UTC),
        service_tokens={"office-api": "svc-office-token"},
    )
    service.bootstrap_superadmin(
        username="viktor.admin",
        display_name="Viktor Johanson",
        password="TempPassw0rd!",
        metadata={"seed": "http"},
    )
    repo.close()


def _start_auth_server(
    db: Path, *, secure_cookie: bool = True
) -> tuple[HTTPServer, threading.Thread, str]:
    ready: queue.Queue[HTTPServer] = queue.Queue()

    def run() -> None:
        from catering_system.ui.employee_auth_api import create_employee_auth_server

        server = create_employee_auth_server(
            db,
            host="127.0.0.1",
            port=0,
            secure_cookie=secure_cookie,
            service_tokens={"office-api": "svc-office-token"},
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
    _seed_auth(db)
    server, thread, base = _start_auth_server(db)
    yield base
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)
    assert thread.is_alive() is False


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


def test_login_logout_me_and_change_password_flow(auth_api) -> None:
    status, body, headers = _request(
        f"{auth_api}/auth/login",
        method="POST",
        body={"username": "viktor.admin", "password": "TempPassw0rd!"},
    )
    assert status == 200
    assert body["account"]["username"] == "viktor.admin"
    assert body["account"]["must_change_password"] is True
    assert body["application_access_allowed"] is False
    assert body["effective_permissions"] == []
    cookie = headers["Set-Cookie"]
    csrf_token = body["csrf_token"]
    assert "Secure" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=Lax" in cookie
    assert "Path=/" in cookie

    status, me, _headers = _request(
        f"{auth_api}/auth/me",
        headers={"Cookie": cookie},
    )
    assert status == 200
    assert me["account"]["role"] == "SUPERADMIN"
    assert me["account"]["must_change_password"] is True
    assert me["application_access_allowed"] is False
    assert me["effective_permissions"] == []

    status, _body, _headers = _request(
        f"{auth_api}/auth/logout",
        method="POST",
        headers={"Cookie": cookie},
    )
    assert status == 401

    status, _body, _headers = _request(
        f"{auth_api}/auth/password/change",
        method="POST",
        headers={"Cookie": cookie, "X-CSRF-Token": csrf_token},
        body={"current_password": "TempPassw0rd!", "new_password": "ChangedPassw0rd!"},
    )
    assert status == 204

    status, _body, _headers = _request(
        f"{auth_api}/auth/me",
        headers={"Cookie": cookie},
    )
    assert status == 401

    status, body, headers = _request(
        f"{auth_api}/auth/login",
        method="POST",
        body={"username": "viktor.admin", "password": "ChangedPassw0rd!"},
    )
    assert status == 200
    assert body["account"]["must_change_password"] is False
    assert body["application_access_allowed"] is True
    assert "settings.edit" in body["effective_permissions"]
    cookie = headers["Set-Cookie"]
    csrf_token = body["csrf_token"]

    status, _body, headers = _request(
        f"{auth_api}/auth/logout",
        method="POST",
        headers={"Cookie": cookie, "X-CSRF-Token": csrf_token},
    )
    assert status == 204
    assert "Max-Age=0" in headers["Set-Cookie"]
    assert "Secure" in headers["Set-Cookie"]
    assert "HttpOnly" in headers["Set-Cookie"]
    assert "SameSite=Lax" in headers["Set-Cookie"]
    assert "Path=/" in headers["Set-Cookie"]


def test_login_rejects_wrong_password(auth_api) -> None:
    status, body, _headers = _request(
        f"{auth_api}/auth/login",
        method="POST",
        body={"username": "viktor.admin", "password": "wrong"},
    )
    assert status == 401
    assert body["error"] == "invalid_credentials"


def test_csrf_required_for_state_changing_requests(auth_api) -> None:
    status, body, headers = _request(
        f"{auth_api}/auth/login",
        method="POST",
        body={"username": "viktor.admin", "password": "TempPassw0rd!"},
    )
    assert status == 200
    cookie = headers["Set-Cookie"]

    status, body, _headers = _request(
        f"{auth_api}/auth/logout",
        method="POST",
        headers={"Cookie": cookie},
    )
    assert status == 401
    assert body["error"] == "unauthorized"


def test_csrf_token_from_another_session_is_rejected(auth_api) -> None:
    status, body, headers = _request(
        f"{auth_api}/auth/login",
        method="POST",
        body={"username": "viktor.admin", "password": "TempPassw0rd!"},
    )
    assert status == 200
    cookie_a = headers["Set-Cookie"]
    csrf_a = body["csrf_token"]

    status, body, headers = _request(
        f"{auth_api}/auth/login",
        method="POST",
        body={"username": "viktor.admin", "password": "TempPassw0rd!"},
    )
    assert status == 200
    cookie_b = headers["Set-Cookie"]
    assert body["csrf_token"] != csrf_a

    status, body, _headers = _request(
        f"{auth_api}/auth/logout",
        method="POST",
        headers={"Cookie": cookie_b, "X-CSRF-Token": csrf_a},
    )
    assert status == 401
    assert body["error"] == "unauthorized"
    status, _body, _headers = _request(
        f"{auth_api}/auth/me",
        headers={"Cookie": cookie_a},
    )
    assert status == 200


def test_introspect_distinguishes_employee_session_service_and_public(auth_api) -> None:
    status, body, headers = _request(
        f"{auth_api}/auth/login",
        method="POST",
        body={"username": "viktor.admin", "password": "TempPassw0rd!"},
    )
    assert status == 200
    cookie = headers["Set-Cookie"]

    status, body, _headers = _request(
        f"{auth_api}/auth/introspect",
        headers={"Cookie": cookie},
    )
    assert status == 200
    assert body["kind"] == "employee_session"
    assert body["authenticated"] is True
    assert body["application_access_allowed"] is False
    assert body["effective_permissions"] == []

    status, body, _headers = _request(
        f"{auth_api}/auth/introspect",
        headers={"Authorization": "Bearer svc-office-token"},
    )
    assert status == 200
    assert body["kind"] == "service_token"
    assert body["service_id"] == "office-api"
    assert body["application_access_allowed"] is False

    status, body, _headers = _request(f"{auth_api}/auth/introspect")
    assert status == 200
    assert body["kind"] == "public"
    assert body["application_access_allowed"] is False


def test_explicit_dev_insecure_mode_omits_secure_cookie(tmp_path: Path) -> None:
    db = tmp_path / "core.db"
    _seed_auth(db)
    server, thread, base = _start_auth_server(db, secure_cookie=False)
    try:
        status, _body, headers = _request(
            f"{base}/auth/login",
            method="POST",
            body={"username": "viktor.admin", "password": "TempPassw0rd!"},
        )
        assert status == 200
        assert "Secure" not in headers["Set-Cookie"]
        assert "HttpOnly" in headers["Set-Cookie"]
        assert "SameSite=Lax" in headers["Set-Cookie"]
        assert "Path=/" in headers["Set-Cookie"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert thread.is_alive() is False
