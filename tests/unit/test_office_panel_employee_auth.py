from __future__ import annotations

import base64
import http.cookiejar
import sqlite3
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

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
    data: dict[str, str] | None = None,
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
    secure_cookie: bool = True,
) -> PanelHarness:
    db = tmp_path / "core.db"
    connection = sqlite3.connect(str(db), check_same_thread=False)
    repo = SQLiteEmployeeAuthRepository.from_connection(connection)
    clock = Clock(datetime(2026, 8, 1, 9, 0, tzinfo=UTC))
    service = EmployeeAuthService(repo, now=clock.now)
    account = service.bootstrap_superadmin(
        username="viktor.admin",
        display_name="Viktor Johanson",
        password="TempPassw0rd!",
        metadata={"seed": "office-panel"},
    )
    assert account.username == "viktor.admin"
    server = create_office_panel_server(
        InMemoryInquiryRepository(),
        InMemoryOrderRepository(),
        password,
        host="127.0.0.1",
        port=0,
        auth_mode=auth_mode,
        auth_service=service,
        secure_cookie=secure_cookie,
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


@pytest.fixture()
def employee_panel(tmp_path: Path):
    panel = _create_panel(tmp_path, auth_mode="employee", secure_cookie=False)
    yield panel
    _shutdown(panel)


@pytest.fixture()
def employee_panel_secure(tmp_path: Path):
    panel = _create_panel(tmp_path, auth_mode="employee", secure_cookie=True)
    yield panel
    _shutdown(panel)


@pytest.fixture()
def migration_panel(tmp_path: Path):
    panel = _create_panel(tmp_path, auth_mode="migration", secure_cookie=False)
    yield panel
    _shutdown(panel)


def test_employee_mode_redirects_unauthenticated_get_to_login(
    employee_panel: PanelHarness,
) -> None:
    status, _url, _body, headers = _request(employee_panel.base, "/")
    assert status == 303
    assert headers["Location"].startswith("/login")


def test_login_page_remains_accessible(employee_panel: PanelHarness) -> None:
    status, _url, body, _headers = _request(employee_panel.base, "/login")
    assert status == 200
    assert "Bitte mit Ihrem Mitarbeiterkonto anmelden." in body


def test_valid_employee_login_sets_secure_cookies_and_redirects(
    employee_panel_secure: PanelHarness,
) -> None:
    jar = http.cookiejar.CookieJar()
    status, _url, _body, headers = _request(
        employee_panel_secure.base,
        "/login",
        method="POST",
        data={"username": "viktor.admin", "password": "TempPassw0rd!", "next": "/"},
        jar=jar,
    )
    assert status == 303
    assert headers["Location"] == "/"
    set_cookies = headers.get_all("Set-Cookie")
    assert set_cookies is not None
    assert any(
        "sl_employee_session=" in value and "Secure" in value for value in set_cookies
    )
    assert any(
        "sl_employee_csrf=" in value and "Secure" in value for value in set_cookies
    )


def test_bad_username_or_password_returns_generic_error(
    employee_panel: PanelHarness,
) -> None:
    status, _url, body, _headers = _request(
        employee_panel.base,
        "/login",
        method="POST",
        data={"username": "viktor.admin", "password": "wrong", "next": "/"},
    )
    assert status == 401
    assert "Anmeldung fehlgeschlagen." in body
    assert "inactive" not in body.lower()


def test_employee_mode_rejects_basic_fallback(employee_panel: PanelHarness) -> None:
    status, _url, _body, headers = _request(
        employee_panel.base,
        "/",
        headers={"Authorization": _auth_header(employee_panel.password)},
    )
    assert status == 303
    assert headers["Location"].startswith("/login")


def test_migration_mode_accepts_basic_fallback_and_displays_warning(
    migration_panel: PanelHarness,
) -> None:
    status, _url, body, _headers = _request(
        migration_panel.base,
        "/",
        headers={"Authorization": _auth_header(migration_panel.password)},
    )
    assert status == 200
    assert "Gemeinsamer Office-Zugang" in body
    assert "Legacy-Zugang" in body
    assert "Übergangsmodus aktiv" in body


def test_must_change_password_redirects_normal_routes(
    employee_panel: PanelHarness,
) -> None:
    jar = http.cookiejar.CookieJar()
    _request(
        employee_panel.base,
        "/login",
        method="POST",
        data={"username": "viktor.admin", "password": "TempPassw0rd!", "next": "/"},
        jar=jar,
    )
    status, _url, _body, headers = _request(employee_panel.base, "/", jar=jar)
    assert status == 303
    assert headers["Location"] == "/password-change"


def test_password_change_page_and_submit_remain_available(
    employee_panel: PanelHarness,
) -> None:
    jar = http.cookiejar.CookieJar()
    _request(
        employee_panel.base,
        "/login",
        method="POST",
        data={"username": "viktor.admin", "password": "TempPassw0rd!", "next": "/"},
        jar=jar,
    )
    status, _url, body, _headers = _request(
        employee_panel.base, "/password-change", jar=jar
    )
    assert status == 200
    assert "Passwort ändern" in body

    csrf_token = _cookie_value(jar, "sl_employee_csrf")
    status, _url, _body, headers = _request(
        employee_panel.base,
        "/password-change",
        method="POST",
        data={
            "_csrf_token": csrf_token,
            "current_password": "TempPassw0rd!",
            "new_password": "ChangedTemp1!",
        },
        jar=jar,
    )
    assert status == 303
    assert headers["Location"] == "/login"
    set_cookies = headers.get_all("Set-Cookie")
    assert set_cookies is not None
    assert any(
        "sl_employee_session=" in value and "Max-Age=0" in value
        for value in set_cookies
    )
    status, _url, _body, headers = _request(employee_panel.base, "/", jar=jar)
    assert status == 303
    assert headers["Location"].startswith("/login")


def test_header_displays_real_employee_identity_and_role(
    employee_panel: PanelHarness,
) -> None:
    login = employee_panel.service.authenticate(
        username="viktor.admin", password="TempPassw0rd!"
    )
    employee = employee_panel.service.authenticate_session(login.session_token)
    employee_panel.service.change_password(
        employee,
        current_password="TempPassw0rd!",
        new_password="ChangedTemp1!",
    )

    jar = http.cookiejar.CookieJar()
    _request(
        employee_panel.base,
        "/login",
        method="POST",
        data={"username": "viktor.admin", "password": "ChangedTemp1!", "next": "/"},
        jar=jar,
    )
    status, _url, body, _headers = _request(employee_panel.base, "/", jar=jar)
    assert status == 200
    assert "Viktor Johanson" in body
    assert "Superadmin" in body


def test_logout_requires_csrf_and_revokes_session(employee_panel: PanelHarness) -> None:
    jar = http.cookiejar.CookieJar()
    _request(
        employee_panel.base,
        "/login",
        method="POST",
        data={"username": "viktor.admin", "password": "TempPassw0rd!", "next": "/"},
        jar=jar,
    )
    status, _url, body, _headers = _request(
        employee_panel.base,
        "/logout",
        method="POST",
        data={},
        jar=jar,
    )
    assert status == 403
    assert "CSRF" in body

    csrf_token = _cookie_value(jar, "sl_employee_csrf")
    status, _url, _body, headers = _request(
        employee_panel.base,
        "/logout",
        method="POST",
        data={"_csrf_token": csrf_token},
        jar=jar,
    )
    assert status == 303
    assert headers["Location"] == "/login"
    status, _url, _body, headers = _request(employee_panel.base, "/", jar=jar)
    assert status == 303
    assert headers["Location"].startswith("/login")


def test_cross_session_csrf_returns_403(employee_panel: PanelHarness) -> None:
    jar_a = http.cookiejar.CookieJar()
    jar_b = http.cookiejar.CookieJar()
    _request(
        employee_panel.base,
        "/login",
        method="POST",
        data={"username": "viktor.admin", "password": "TempPassw0rd!", "next": "/"},
        jar=jar_a,
    )
    _request(
        employee_panel.base,
        "/login",
        method="POST",
        data={"username": "viktor.admin", "password": "TempPassw0rd!", "next": "/"},
        jar=jar_b,
    )
    status, _url, body, _headers = _request(
        employee_panel.base,
        "/logout",
        method="POST",
        data={"_csrf_token": _cookie_value(jar_a, "sl_employee_csrf")},
        jar=jar_b,
    )
    assert status == 403
    assert "CSRF" in body


def test_employee_session_takes_precedence_over_basic_fallback(
    migration_panel: PanelHarness,
) -> None:
    login = migration_panel.service.authenticate(
        username="viktor.admin", password="TempPassw0rd!"
    )
    employee = migration_panel.service.authenticate_session(login.session_token)
    migration_panel.service.change_password(
        employee,
        current_password="TempPassw0rd!",
        new_password="ChangedTemp1!",
    )

    jar = http.cookiejar.CookieJar()
    _request(
        migration_panel.base,
        "/login",
        method="POST",
        data={"username": "viktor.admin", "password": "ChangedTemp1!", "next": "/"},
        jar=jar,
    )
    status, _url, body, _headers = _request(
        migration_panel.base,
        "/",
        headers={"Authorization": _auth_header(migration_panel.password)},
        jar=jar,
    )
    assert status == 200
    assert "Viktor Johanson" in body
    assert "Gemeinsamer Office-Zugang" not in body


def test_revoked_session_redirects_back_to_login(employee_panel: PanelHarness) -> None:
    jar = http.cookiejar.CookieJar()
    _request(
        employee_panel.base,
        "/login",
        method="POST",
        data={"username": "viktor.admin", "password": "TempPassw0rd!", "next": "/"},
        jar=jar,
    )
    session_token = _cookie_value(jar, "sl_employee_session")
    employee = employee_panel.service.authenticate_session(session_token)
    employee_panel.service.logout(employee)
    status, _url, _body, headers = _request(employee_panel.base, "/", jar=jar)
    assert status == 303
    assert headers["Location"].startswith("/login")


def test_inactive_account_cannot_log_in(employee_panel: PanelHarness) -> None:
    login = employee_panel.service.authenticate(
        username="viktor.admin", password="TempPassw0rd!"
    )
    employee = employee_panel.service.authenticate_session(login.session_token)
    employee_panel.service.change_password(
        employee,
        current_password="TempPassw0rd!",
        new_password="ChangedTemp1!",
    )
    admin_login = employee_panel.service.authenticate(
        username="viktor.admin", password="ChangedTemp1!"
    )
    admin = employee_panel.service.authenticate_session(admin_login.session_token)
    worker = employee_panel.service.create_account(
        admin,
        username="worker.inactive",
        display_name="Worker Inactive",
        password="AnotherTemp1!",
        role="USER",
    )
    employee_panel.service.deactivate_account(admin, worker.id)
    status, _url, body, _headers = _request(
        employee_panel.base,
        "/login",
        method="POST",
        data={"username": "worker.inactive", "password": "AnotherTemp1!", "next": "/"},
    )
    assert status == 401
    assert "Anmeldung fehlgeschlagen." in body


def test_unknown_auth_mode_fails_startup(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown office auth mode"):
        create_office_panel_server(
            InMemoryInquiryRepository(),
            InMemoryOrderRepository(),
            "shared-office-password",
            host="127.0.0.1",
            port=0,
            auth_mode="mystery",
        )


def test_open_redirect_attempt_is_rejected(employee_panel: PanelHarness) -> None:
    status, _url, _body, headers = _request(
        employee_panel.base,
        "/login",
        method="POST",
        data={
            "username": "viktor.admin",
            "password": "TempPassw0rd!",
            "next": "https://evil.example/steal",
        },
    )
    assert status == 303
    assert headers["Location"] == "/"


def test_login_redirect_preserves_safe_internal_target(
    employee_panel: PanelHarness,
) -> None:
    status, _url, _body, headers = _request(
        employee_panel.base,
        "/login",
        method="POST",
        data={
            "username": "viktor.admin",
            "password": "TempPassw0rd!",
            "next": "/angebote",
        },
    )
    assert status == 303
    assert headers["Location"] == "/angebote"


def test_last_seen_writes_are_bounded_in_practice(employee_panel: PanelHarness) -> None:
    jar = http.cookiejar.CookieJar()
    _request(
        employee_panel.base,
        "/login",
        method="POST",
        data={"username": "viktor.admin", "password": "TempPassw0rd!", "next": "/"},
        jar=jar,
    )
    session_token = _cookie_value(jar, "sl_employee_session")
    employee = employee_panel.service.authenticate_session(session_token)
    first_seen = employee.session.last_seen_at

    employee_panel.clock.value = employee_panel.clock.value + timedelta(minutes=4)
    employee = employee_panel.service.authenticate_session(session_token)
    assert employee.session.last_seen_at == first_seen

    employee_panel.clock.value = employee_panel.clock.value + timedelta(minutes=1)
    employee = employee_panel.service.authenticate_session(session_token)
    assert employee.session.last_seen_at == employee_panel.clock.value
