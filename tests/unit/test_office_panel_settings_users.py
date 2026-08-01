from __future__ import annotations

import base64
import http.cookiejar
import re
import sqlite3
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

from catering_system.domain.employee_auth import PERMISSION_REGISTRY
from catering_system.repositories.in_memory_inquiry_repository import (
    InMemoryInquiryRepository,
)
from catering_system.repositories.in_memory_order_repository import (
    InMemoryOrderRepository,
)
from catering_system.repositories.sqlite_employee_auth_repository import (
    SQLiteEmployeeAuthRepository,
)
from catering_system.services.employee_auth_service import EmployeeAuthService
from catering_system.ui.office_panel import create_office_panel_server


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Clock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def now(self) -> datetime:
        return self.value


@dataclass
class PanelHarness:
    base: str
    server: object
    thread: threading.Thread
    service: EmployeeAuthService
    repo: SQLiteEmployeeAuthRepository
    clock: Clock
    password: str


def _auth_header(password: str) -> str:
    return "Basic " + base64.b64encode(f"office:{password}".encode()).decode()


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
    data: dict[str, str] | list[tuple[str, str]] | None = None,
    headers: dict[str, str] | None = None,
    jar: http.cookiejar.CookieJar | None = None,
) -> tuple[int, str, str, object]:
    cookie_jar = jar if jar is not None else http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(
        _NoRedirect,
        urllib.request.HTTPCookieProcessor(cookie_jar),
    )
    payload = None
    if data is not None:
        if isinstance(data, list):
            payload = urllib.parse.urlencode(data, doseq=True).encode()
        else:
            payload = urllib.parse.urlencode(data).encode()
    request = urllib.request.Request(
        f"{base}{path}",
        data=payload,
        method=method,
    )
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    try:
        with opener.open(request) as response:
            return (
                response.status,
                response.url,
                response.read().decode("utf-8"),
                response.headers,
            )
    except urllib.error.HTTPError as exc:
        return exc.code, exc.geturl(), exc.read().decode("utf-8"), exc.headers


def _create_panel(
    tmp_path: Path,
    *,
    auth_mode: str,
    password: str = "shared-office-password",
) -> PanelHarness:
    db = tmp_path / "core.db"
    connection = sqlite3.connect(str(db), check_same_thread=False)
    repo = SQLiteEmployeeAuthRepository.from_connection(connection)
    clock = Clock(datetime(2026, 8, 1, 9, 0, tzinfo=UTC))
    service = EmployeeAuthService(repo, now=clock.now)
    service.bootstrap_superadmin(
        username="viktor.admin",
        display_name="Viktor Johanson",
        password="TempPassw0rd!",
        metadata={"seed": "settings-users"},
    )
    server = create_office_panel_server(
        InMemoryInquiryRepository(),
        InMemoryOrderRepository(),
        password,
        host="127.0.0.1",
        port=0,
        auth_mode=auth_mode,
        auth_service=service,
        secure_cookie=False,
        ui_version="v2",
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    return PanelHarness(
        base=f"http://{host}:{port}",
        server=server,
        thread=thread,
        service=service,
        repo=repo,
        clock=clock,
        password=password,
    )


def _shutdown(panel: PanelHarness) -> None:
    panel.server.shutdown()
    panel.server.server_close()
    panel.thread.join(timeout=5)
    panel.repo.close()


def _login(
    panel: PanelHarness, *, username: str, password: str
) -> http.cookiejar.CookieJar:
    jar = http.cookiejar.CookieJar()
    _request(
        panel.base,
        "/login",
        method="POST",
        data={"username": username, "password": password, "next": "/"},
        jar=jar,
    )
    return jar


def _ready_superadmin(panel: PanelHarness) -> http.cookiejar.CookieJar:
    jar = _login(panel, username="viktor.admin", password="TempPassw0rd!")
    employee = panel.service.authenticate_session(
        _cookie_value(jar, "sl_employee_session")
    )
    panel.service.change_password(
        employee,
        current_password="TempPassw0rd!",
        new_password="ChangedTemp1!",
    )
    return _login(panel, username="viktor.admin", password="ChangedTemp1!")


def _csrf(jar: http.cookiejar.CookieJar) -> str:
    return _cookie_value(jar, "sl_employee_csrf")


def _ready_admin(
    panel: PanelHarness, super_jar: http.cookiejar.CookieJar
) -> http.cookiejar.CookieJar:
    super_employee = panel.service.authenticate_session(
        _cookie_value(super_jar, "sl_employee_session")
    )
    admin = panel.service.create_account(
        super_employee,
        username="team.admin",
        display_name="Team Admin",
        password="AdminTemp1!",
        role="ADMIN",
    )
    jar = _login(panel, username=admin.username, password="AdminTemp1!")
    employee = panel.service.authenticate_session(
        _cookie_value(jar, "sl_employee_session")
    )
    panel.service.change_password(
        employee,
        current_password="AdminTemp1!",
        new_password="AdminChanged1!",
    )
    return _login(panel, username=admin.username, password="AdminChanged1!")


@pytest.fixture()
def employee_panel(tmp_path: Path):
    panel = _create_panel(tmp_path, auth_mode="employee")
    yield panel
    _shutdown(panel)


@pytest.fixture()
def migration_panel(tmp_path: Path):
    panel = _create_panel(tmp_path, auth_mode="migration")
    yield panel
    _shutdown(panel)


def test_users_nav_visible_with_users_view(employee_panel: PanelHarness) -> None:
    jar = _ready_superadmin(employee_panel)
    status, _url, body, _headers = _request(employee_panel.base, "/", jar=jar)
    assert status == 200
    assert "Benutzer &amp; Rechte" in body or "Benutzer & Rechte" in body
    assert 'href="/settings/users"' in body


def test_users_nav_hidden_without_users_view(employee_panel: PanelHarness) -> None:
    super_jar = _ready_superadmin(employee_panel)
    super_employee = employee_panel.service.authenticate_session(
        _cookie_value(super_jar, "sl_employee_session")
    )
    viewer = employee_panel.service.create_account(
        super_employee,
        username="reader.only",
        display_name="Reader Only",
        password="ViewerTemp1!",
        role="VIEWER",
        explicit_permissions={"inquiries.view"},
    )
    jar = _login(employee_panel, username=viewer.username, password="ViewerTemp1!")
    employee = employee_panel.service.authenticate_session(
        _cookie_value(jar, "sl_employee_session")
    )
    employee_panel.service.change_password(
        employee,
        current_password="ViewerTemp1!",
        new_password="ViewerChanged1!",
    )
    jar = _login(employee_panel, username=viewer.username, password="ViewerChanged1!")
    status, _url, body, _headers = _request(employee_panel.base, "/anfragen", jar=jar)
    assert status == 200
    assert "/settings/users" not in body


def test_basic_fallback_cannot_access_users_routes(
    migration_panel: PanelHarness,
) -> None:
    status, _url, body, _headers = _request(
        migration_panel.base,
        "/settings/users",
        headers={"Authorization": _auth_header(migration_panel.password)},
    )
    assert status == 403
    assert "Berechtigung" in body


def test_unauthenticated_users_route_redirects_to_login(
    employee_panel: PanelHarness,
) -> None:
    status, _url, _body, headers = _request(employee_panel.base, "/settings/users")
    assert status == 303
    assert headers["Location"].startswith("/login")


def test_list_page_shows_account_fields(employee_panel: PanelHarness) -> None:
    jar = _ready_superadmin(employee_panel)
    super_employee = employee_panel.service.authenticate_session(
        _cookie_value(jar, "sl_employee_session")
    )
    employee_panel.service.create_account(
        super_employee,
        username="worker.one",
        display_name="Worker One",
        password="WorkerTemp1!",
        role="USER",
        email="worker@example.com",
    )
    status, _url, body, _headers = _request(
        employee_panel.base, "/settings/users", jar=jar
    )
    assert status == 200
    assert "Worker One" in body
    assert "worker.one" in body
    assert "worker@example.com" in body
    assert "Benutzer" in body


def test_admin_sees_admin_rows_read_only(employee_panel: PanelHarness) -> None:
    super_jar = _ready_superadmin(employee_panel)
    admin_jar = _ready_admin(employee_panel, super_jar)
    status, _url, body, _headers = _request(
        employee_panel.base, "/settings/users", jar=admin_jar
    )
    assert status == 200
    assert "Nur Lesen" in body
    assert "viktor.admin" in body


def test_superadmin_can_open_editable_account_detail(
    employee_panel: PanelHarness,
) -> None:
    jar = _ready_superadmin(employee_panel)
    super_employee = employee_panel.service.authenticate_session(
        _cookie_value(jar, "sl_employee_session")
    )
    worker = employee_panel.service.create_account(
        super_employee,
        username="editable.user",
        display_name="Editable User",
        password="WorkerTemp1!",
        role="USER",
    )
    status, _url, body, _headers = _request(
        employee_panel.base,
        f"/settings/users/{worker.id}",
        jar=jar,
    )
    assert status == 200
    assert worker.id in body
    assert "Profil speichern" in body
    assert "Passwort zurücksetzen" not in body or "Temporäres Passwort setzen" in body


def test_create_user_succeeds(employee_panel: PanelHarness) -> None:
    jar = _ready_superadmin(employee_panel)
    status, _url, _body, headers = _request(
        employee_panel.base,
        "/settings/users",
        method="POST",
        data={
            "_csrf_token": _csrf(jar),
            "username": "new.worker",
            "display_name": "New Worker",
            "email": "new@example.com",
            "role": "USER",
            "temporary_password": "WorkerTemp1!",
        },
        jar=jar,
    )
    assert status == 303
    assert "/settings/users/" in headers["Location"]
    assert "msg=created" in headers["Location"]


def test_create_viewer_exposes_only_read_permissions(
    employee_panel: PanelHarness,
) -> None:
    jar = _ready_superadmin(employee_panel)
    super_employee = employee_panel.service.authenticate_session(
        _cookie_value(jar, "sl_employee_session")
    )
    viewer = employee_panel.service.create_account(
        super_employee,
        username="viewer.perms",
        display_name="Viewer Perms",
        password="ViewerTemp1!",
        role="VIEWER",
        explicit_permissions={"inquiries.view"},
    )
    status, _url, body, _headers = _request(
        employee_panel.base,
        f"/settings/users/{viewer.id}",
        jar=jar,
    )
    assert status == 200
    assert "Für Leser nur Leseberechtigungen" in body
    assert 'name="permission" value="inquiries.create"' not in body


def test_admin_cannot_select_admin_role_on_create(employee_panel: PanelHarness) -> None:
    super_jar = _ready_superadmin(employee_panel)
    admin_jar = _ready_admin(employee_panel, super_jar)
    status, _url, body, _headers = _request(
        employee_panel.base, "/settings/users/new", jar=admin_jar
    )
    assert status == 200
    assert "SUPERADMIN" not in body
    assert "ADMIN" not in body or "Administrator" not in body.split("select")[1][:200]
    status, _url, _body, headers = _request(
        employee_panel.base,
        "/settings/users",
        method="POST",
        data={
            "_csrf_token": _csrf(admin_jar),
            "username": "blocked.admin",
            "display_name": "Blocked Admin",
            "role": "ADMIN",
            "temporary_password": "AdminTemp1!",
        },
        jar=admin_jar,
    )
    assert status in {403, 409}
    assert headers.get("Location") is None or "blocked.admin" not in headers["Location"]


def test_username_conflict_renders_german_error(employee_panel: PanelHarness) -> None:
    jar = _ready_superadmin(employee_panel)
    payload = {
        "_csrf_token": _csrf(jar),
        "username": "dup.user",
        "display_name": "Dup User",
        "role": "USER",
        "temporary_password": "WorkerTemp1!",
    }
    _request(
        employee_panel.base,
        "/settings/users",
        method="POST",
        data=payload,
        jar=jar,
    )
    status, _url, body, _headers = _request(
        employee_panel.base,
        "/settings/users",
        method="POST",
        data=payload,
        jar=jar,
    )
    assert status == 409
    assert "Benutzername ist bereits vergeben." in body
    assert 'type="password"' in body
    assert 'value="WorkerTemp1!"' not in body


def test_profile_edit_preserves_account_id(employee_panel: PanelHarness) -> None:
    jar = _ready_superadmin(employee_panel)
    super_employee = employee_panel.service.authenticate_session(
        _cookie_value(jar, "sl_employee_session")
    )
    worker = employee_panel.service.create_account(
        super_employee,
        username="profile.user",
        display_name="Profile User",
        password="WorkerTemp1!",
        role="USER",
    )
    status, _url, body, _headers = _request(
        employee_panel.base,
        f"/settings/users/{worker.id}/profile",
        method="POST",
        data={
            "_csrf_token": _csrf(jar),
            "username": "profile.user",
            "display_name": "Updated Profile",
            "email": "",
        },
        jar=jar,
    )
    assert status == 303
    status, _url, body, _headers = _request(
        employee_panel.base,
        f"/settings/users/{worker.id}?msg=saved",
        jar=jar,
    )
    assert worker.id in body
    assert "Updated Profile" in body


def test_role_change_refreshes_effective_permissions(
    employee_panel: PanelHarness,
) -> None:
    jar = _ready_superadmin(employee_panel)
    super_employee = employee_panel.service.authenticate_session(
        _cookie_value(jar, "sl_employee_session")
    )
    worker = employee_panel.service.create_account(
        super_employee,
        username="role.user",
        display_name="Role User",
        password="WorkerTemp1!",
        role="USER",
        explicit_permissions={"inquiries.view", "inquiries.create"},
    )
    status, _url, _body, headers = _request(
        employee_panel.base,
        f"/settings/users/{worker.id}/role",
        method="POST",
        data={"_csrf_token": _csrf(jar), "role": "VIEWER"},
        jar=jar,
    )
    assert status == 303
    assert "role_changed" in headers["Location"]
    detail = employee_panel.service.get_account(super_employee, worker.id)
    assert "inquiries.create" not in detail.effective_permissions


def test_permission_matrix_uses_canonical_registry(
    employee_panel: PanelHarness,
) -> None:
    jar = _ready_superadmin(employee_panel)
    super_employee = employee_panel.service.authenticate_session(
        _cookie_value(jar, "sl_employee_session")
    )
    worker = employee_panel.service.create_account(
        super_employee,
        username="perm.user",
        display_name="Perm User",
        password="WorkerTemp1!",
        role="USER",
    )
    status, _url, body, _headers = _request(
        employee_panel.base,
        f"/settings/users/{worker.id}",
        jar=jar,
    )
    assert status == 200
    for code in PERMISSION_REGISTRY:
        assert code in body


def test_unavailable_permissions_not_submitted_via_form(
    employee_panel: PanelHarness,
) -> None:
    super_jar = _ready_superadmin(employee_panel)
    admin_jar = _ready_admin(employee_panel, super_jar)
    super_employee = employee_panel.service.authenticate_session(
        _cookie_value(super_jar, "sl_employee_session")
    )
    worker = employee_panel.service.create_account(
        super_employee,
        username="perm.target",
        display_name="Perm Target",
        password="WorkerTemp1!",
        role="USER",
    )
    status, _url, _body, headers = _request(
        employee_panel.base,
        f"/settings/users/{worker.id}/permissions",
        method="POST",
        data=[
            ("_csrf_token", _csrf(admin_jar)),
            ("permission", "settings.edit"),
            ("permission", "inquiries.view"),
        ],
        jar=admin_jar,
    )
    assert status == 303
    detail = employee_panel.service.get_account(super_employee, worker.id)
    assert "settings.edit" not in detail.explicit_permissions


def test_forged_post_still_denied_by_service(
    employee_panel: PanelHarness,
) -> None:
    super_jar = _ready_superadmin(employee_panel)
    admin_jar = _ready_admin(employee_panel, super_jar)
    super_employee = employee_panel.service.authenticate_session(
        _cookie_value(super_jar, "sl_employee_session")
    )
    status, _url, body, _headers = _request(
        employee_panel.base,
        f"/settings/users/{super_employee.account.id}/profile",
        method="POST",
        data={
            "_csrf_token": _csrf(admin_jar),
            "username": super_employee.account.username,
            "display_name": "Hack",
            "email": "",
        },
        jar=admin_jar,
    )
    assert status in {400, 403}
    assert "nicht zulässig" in body or "Berechtigung" in body


def test_deactivate_confirmation_and_success(employee_panel: PanelHarness) -> None:
    jar = _ready_superadmin(employee_panel)
    super_employee = employee_panel.service.authenticate_session(
        _cookie_value(jar, "sl_employee_session")
    )
    worker = employee_panel.service.create_account(
        super_employee,
        username="deact.user",
        display_name="Deact User",
        password="WorkerTemp1!",
        role="USER",
    )
    status, _url, body, _headers = _request(
        employee_panel.base,
        f"/settings/users/{worker.id}/deactivate",
        jar=jar,
    )
    assert status == 200
    assert "Sitzungen werden beendet" in body or "Sitzungen" in body
    status, _url, _body, headers = _request(
        employee_panel.base,
        f"/settings/users/{worker.id}/deactivate",
        method="POST",
        data={"_csrf_token": _csrf(jar)},
        jar=jar,
    )
    assert status == 303
    assert "deactivated" in headers["Location"]


def test_last_active_superadmin_conflict_rendered_safely(
    employee_panel: PanelHarness,
) -> None:
    jar = _ready_superadmin(employee_panel)
    super_employee = employee_panel.service.authenticate_session(
        _cookie_value(jar, "sl_employee_session")
    )
    status, _url, body, _headers = _request(
        employee_panel.base,
        f"/settings/users/{super_employee.account.id}/deactivate",
        method="POST",
        data={"_csrf_token": _csrf(jar)},
        jar=jar,
    )
    assert status == 400
    assert "letzte aktive Superadmin" in body


def test_reactivate_success(employee_panel: PanelHarness) -> None:
    jar = _ready_superadmin(employee_panel)
    super_employee = employee_panel.service.authenticate_session(
        _cookie_value(jar, "sl_employee_session")
    )
    worker = employee_panel.service.create_account(
        super_employee,
        username="react.user",
        display_name="React User",
        password="WorkerTemp1!",
        role="USER",
    )
    employee_panel.service.deactivate_account(super_employee, worker.id)
    status, _url, _body, headers = _request(
        employee_panel.base,
        f"/settings/users/{worker.id}/reactivate",
        method="POST",
        data={"_csrf_token": _csrf(jar)},
        jar=jar,
    )
    assert status == 303
    assert "reactivated" in headers["Location"]


def test_password_reset_does_not_echo_password(employee_panel: PanelHarness) -> None:
    jar = _ready_superadmin(employee_panel)
    super_employee = employee_panel.service.authenticate_session(
        _cookie_value(jar, "sl_employee_session")
    )
    worker = employee_panel.service.create_account(
        super_employee,
        username="reset.user",
        display_name="Reset User",
        password="WorkerTemp1!",
        role="USER",
    )
    temp = "ResetTemp1!"
    status, _url, body, _headers = _request(
        employee_panel.base,
        f"/settings/users/{worker.id}/reset-password",
        method="POST",
        data={
            "_csrf_token": _csrf(jar),
            "temporary_password": temp,
            "temporary_password_confirm": temp,
        },
        jar=jar,
    )
    assert status == 303
    status, _url, body, _headers = _request(
        employee_panel.base,
        f"/settings/users/{worker.id}?msg=password_reset",
        jar=jar,
    )
    assert temp not in body


def test_password_reset_success_message(employee_panel: PanelHarness) -> None:
    jar = _ready_superadmin(employee_panel)
    super_employee = employee_panel.service.authenticate_session(
        _cookie_value(jar, "sl_employee_session")
    )
    worker = employee_panel.service.create_account(
        super_employee,
        username="reset.msg",
        display_name="Reset Msg",
        password="WorkerTemp1!",
        role="USER",
    )
    temp = "ResetTemp1!"
    _request(
        employee_panel.base,
        f"/settings/users/{worker.id}/reset-password",
        method="POST",
        data={
            "_csrf_token": _csrf(jar),
            "temporary_password": temp,
            "temporary_password_confirm": temp,
        },
        jar=jar,
    )
    status, _url, body, _headers = _request(
        employee_panel.base,
        f"/settings/users/{worker.id}?msg=password_reset",
        jar=jar,
    )
    assert "Passwortänderung" in body
    assert "Sitzungen" in body


def test_audit_history_renders_redacted_fields(employee_panel: PanelHarness) -> None:
    jar = _ready_superadmin(employee_panel)
    super_employee = employee_panel.service.authenticate_session(
        _cookie_value(jar, "sl_employee_session")
    )
    worker = employee_panel.service.create_account(
        super_employee,
        username="audit.user",
        display_name="Audit User",
        password="WorkerTemp1!",
        role="USER",
    )
    status, _url, body, _headers = _request(
        employee_panel.base,
        f"/settings/users/{worker.id}",
        jar=jar,
    )
    assert status == 200
    assert "auth.account_created" in body
    assert "password_hash" not in body
    assert "csrf" not in body.lower() or "CSRF" not in body


def test_employee_csrf_missing_returns_403(employee_panel: PanelHarness) -> None:
    jar = _ready_superadmin(employee_panel)
    status, _url, body, _headers = _request(
        employee_panel.base,
        "/settings/users",
        method="POST",
        data={"username": "x", "display_name": "X", "role": "USER"},
        jar=jar,
    )
    assert status == 403
    assert "CSRF" in body


def test_cross_session_csrf_returns_403(employee_panel: PanelHarness) -> None:
    jar_a = _ready_superadmin(employee_panel)
    jar_b = _login(employee_panel, username="viktor.admin", password="ChangedTemp1!")
    status, _url, body, _headers = _request(
        employee_panel.base,
        "/logout",
        method="POST",
        data={"_csrf_token": _csrf(jar_a)},
        jar=jar_b,
    )
    assert status == 403


def test_migration_mode_employee_can_access_users(
    migration_panel: PanelHarness,
) -> None:
    jar = _ready_superadmin(migration_panel)
    status, _url, body, _headers = _request(
        migration_panel.base,
        "/settings/users",
        jar=jar,
    )
    assert status == 200
    assert "Benutzer" in body


def test_migration_mode_basic_fallback_denied(migration_panel: PanelHarness) -> None:
    status, _url, body, _headers = _request(
        migration_panel.base,
        "/settings/users",
        headers={"Authorization": _auth_header(migration_panel.password)},
    )
    assert status == 403


def test_no_delete_action_exists(employee_panel: PanelHarness) -> None:
    jar = _ready_superadmin(employee_panel)
    status, _url, body, _headers = _request(
        employee_panel.base, "/settings/users", jar=jar
    )
    assert status == 200
    assert re.search(r">Löschen<|/delete", body, re.IGNORECASE) is None


def test_sidebar_shows_real_employee_identity(employee_panel: PanelHarness) -> None:
    jar = _ready_superadmin(employee_panel)
    status, _url, body, _headers = _request(
        employee_panel.base, "/settings/users", jar=jar
    )
    assert status == 200
    assert "Viktor Johanson" in body
    assert "Superadmin" in body
    assert "Gemeinsamer Office-Zugang" not in body


def test_existing_home_route_still_works(employee_panel: PanelHarness) -> None:
    jar = _ready_superadmin(employee_panel)
    status, _url, body, _headers = _request(employee_panel.base, "/", jar=jar)
    assert status == 200
    assert "Arbeitszentrale" in body
