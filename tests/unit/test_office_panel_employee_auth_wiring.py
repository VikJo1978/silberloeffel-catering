"""Production Office Panel employee-auth runtime wiring tests (AUTH-2C)."""

from __future__ import annotations

import http.cookiejar
import queue
import sqlite3
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
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
from catering_system.repositories.sqlite_employee_auth_repository import (
    SQLiteEmployeeAuthRepository,
)
from catering_system.services.employee_auth_service import LastActiveSuperadminError
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
class WiredPanel:
    base: str
    server: object
    thread: threading.Thread
    runtime: ManagedEmployeeAuthRuntime
    db: Path


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
    request = urllib.request.Request(
        f"{base}{path}",
        data=payload,
        method=method,
    )
    try:
        with opener.open(request) as response:
            return response.status, response.read().decode("utf-8"), response.headers
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8"), exc.headers


def _fresh_repository(db: Path) -> SQLiteEmployeeAuthRepository:
    return SQLiteEmployeeAuthRepository(db)


def _start_wired_panel(tmp_path: Path) -> WiredPanel:
    db = tmp_path / "core.db"
    clock = Clock(datetime(2026, 8, 1, 9, 0, tzinfo=UTC))
    ready: queue.Queue[tuple[object, ManagedEmployeeAuthRuntime]] = queue.Queue()

    def run() -> None:
        runtime = open_managed_employee_auth_runtime(db, now=clock.now)
        runtime.service.bootstrap_superadmin(
            username="viktor.admin",
            display_name="Viktor Johanson",
            password="TempPassw0rd!",
            metadata={"seed": "office-panel-wiring"},
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
        ready.put((server, runtime))
        server.serve_forever()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    server, runtime = ready.get(timeout=5)
    host, port = server.server_address[:2]
    return WiredPanel(
        base=f"http://{host}:{port}",
        server=server,
        thread=thread,
        runtime=runtime,
        db=db,
    )


def _shutdown(panel: WiredPanel) -> None:
    panel.server.shutdown()
    panel.server.server_close()
    panel.thread.join(timeout=5)


def _ready_superadmin_jar(panel: WiredPanel) -> http.cookiejar.CookieJar:
    jar = http.cookiejar.CookieJar()
    _request(
        panel.base,
        "/login",
        method="POST",
        data={"username": "viktor.admin", "password": "TempPassw0rd!", "next": "/"},
        jar=jar,
    )
    _request(
        panel.base,
        "/password-change",
        method="POST",
        data={
            "_csrf_token": _cookie_value(jar, "sl_employee_csrf"),
            "current_password": "TempPassw0rd!",
            "new_password": "ChangedTemp1!",
        },
        jar=jar,
    )
    jar = http.cookiejar.CookieJar()
    _request(
        panel.base,
        "/login",
        method="POST",
        data={"username": "viktor.admin", "password": "ChangedTemp1!", "next": "/"},
        jar=jar,
    )
    return jar


def _create_worker(
    panel: WiredPanel, jar: http.cookiejar.CookieJar, *, username: str
) -> str:
    status, _body, headers = _request(
        panel.base,
        "/settings/users",
        method="POST",
        data={
            "_csrf_token": _cookie_value(jar, "sl_employee_csrf"),
            "username": username,
            "display_name": "Worker Wiring",
            "role": "USER",
            "temporary_password": "WorkerTemp1!",
        },
        jar=jar,
    )
    assert status == 303
    location = headers["Location"]
    account_id = location.split("/settings/users/", 1)[1].split("?", 1)[0]
    return account_id


@pytest.fixture()
def wired_panel(tmp_path: Path):
    panel = _start_wired_panel(tmp_path)
    yield panel
    _shutdown(panel)


def test_open_managed_employee_auth_runtime_uses_managed_transactions(
    tmp_path: Path,
) -> None:
    runtime = open_managed_employee_auth_runtime(tmp_path / "managed.db")
    try:
        assert runtime.repository._manage_transactions is True
        assert not runtime.repository._conn.in_transaction
        with runtime.repository.immediate_transaction():
            assert runtime.repository._conn.in_transaction
        assert not runtime.repository._conn.in_transaction
    finally:
        runtime.close()


def test_office_panel_profile_update_rolls_back_when_success_audit_fails(
    wired_panel: WiredPanel,
) -> None:
    jar = _ready_superadmin_jar(wired_panel)
    worker_id = _create_worker(wired_panel, jar, username="worker.profile.rollback")

    verify_before = _fresh_repository(wired_panel.db)
    try:
        before = verify_before.get_account_by_id(worker_id)
        assert before is not None
        assert before.display_name == "Worker Wiring"
    finally:
        verify_before.close()

    original_append = wired_panel.runtime.service._append_audit

    def failing_append(**kwargs: object) -> None:
        if kwargs.get("action") == "auth.account_profile_updated":
            raise sqlite3.OperationalError("audit insert failed")
        original_append(**kwargs)  # type: ignore[arg-type]

    wired_panel.runtime.service._append_audit = failing_append  # type: ignore[method-assign]

    status, body, _headers = _request(
        wired_panel.base,
        f"/settings/users/{worker_id}/profile",
        method="POST",
        data={
            "_csrf_token": _cookie_value(jar, "sl_employee_csrf"),
            "username": "worker.profile.rollback",
            "display_name": "Should Roll Back",
            "email": "",
        },
        jar=jar,
    )
    assert status == 500
    assert "Die Aktion konnte nicht ausgeführt werden." in body

    verify_after = _fresh_repository(wired_panel.db)
    try:
        after = verify_after.get_account_by_id(worker_id)
        assert after is not None
        assert after.display_name == "Worker Wiring"
        events = verify_after.list_audit_events_for_account(worker_id, limit=100)
        assert not any(
            event.action == "auth.account_profile_updated"
            and event.outcome == "success"
            for event in events
        )
    finally:
        verify_after.close()


def test_office_panel_password_reset_rolls_back_when_success_audit_fails(
    wired_panel: WiredPanel,
) -> None:
    jar = _ready_superadmin_jar(wired_panel)
    worker_id = _create_worker(wired_panel, jar, username="worker.reset.rollback")

    _request(
        wired_panel.base,
        "/login",
        method="POST",
        data={
            "username": "worker.reset.rollback",
            "password": "WorkerTemp1!",
            "next": "/",
        },
    )

    verify_before = _fresh_repository(wired_panel.db)
    try:
        before = verify_before.get_account_by_id(worker_id)
        assert before is not None
        original_hash = before.password_hash
        original_auth_version = before.auth_version
        original_must_change = before.must_change_password
        sessions = verify_before._conn.execute(
            "SELECT revoked_at FROM employee_sessions WHERE account_id = ?",
            (worker_id,),
        ).fetchall()
        assert sessions
        assert all(row[0] is None for row in sessions)
    finally:
        verify_before.close()

    original_append = wired_panel.runtime.service._append_audit

    def failing_append(**kwargs: object) -> None:
        if kwargs.get("action") == "auth.password_reset":
            raise sqlite3.OperationalError("audit insert failed")
        original_append(**kwargs)  # type: ignore[arg-type]

    wired_panel.runtime.service._append_audit = failing_append  # type: ignore[method-assign]

    status, _body, _headers = _request(
        wired_panel.base,
        f"/settings/users/{worker_id}/reset-password",
        method="POST",
        data={
            "_csrf_token": _cookie_value(jar, "sl_employee_csrf"),
            "temporary_password": "ResetTemp1!",
            "temporary_password_confirm": "ResetTemp1!",
        },
        jar=jar,
    )
    assert status == 500

    verify_after = _fresh_repository(wired_panel.db)
    try:
        after = verify_after.get_account_by_id(worker_id)
        assert after is not None
        assert after.password_hash == original_hash
        assert after.auth_version == original_auth_version
        assert after.must_change_password == original_must_change
        sessions = verify_after._conn.execute(
            "SELECT revoked_at FROM employee_sessions WHERE account_id = ?",
            (worker_id,),
        ).fetchall()
        assert sessions
        assert all(row[0] is None for row in sessions)
        events = verify_after.list_audit_events_for_account(worker_id, limit=100)
        assert not any(
            event.action == "auth.password_reset" and event.outcome == "success"
            for event in events
        )
    finally:
        verify_after.close()


def test_office_panel_deactivate_rolls_back_when_success_audit_fails(
    wired_panel: WiredPanel,
) -> None:
    jar = _ready_superadmin_jar(wired_panel)
    worker_id = _create_worker(wired_panel, jar, username="worker.deact.rollback")

    verify_before = _fresh_repository(wired_panel.db)
    try:
        before = verify_before.get_account_by_id(worker_id)
        assert before is not None
        assert before.is_active is True
        assert before.deactivated_at is None
        sessions = verify_before._conn.execute(
            "SELECT revoked_at FROM employee_sessions WHERE account_id = ?",
            (worker_id,),
        ).fetchall()
        assert not sessions or all(row[0] is None for row in sessions)
    finally:
        verify_before.close()

    original_append = wired_panel.runtime.service._append_audit

    def failing_append(**kwargs: object) -> None:
        if kwargs.get("action") == "auth.account_deactivated":
            raise sqlite3.OperationalError("audit insert failed")
        original_append(**kwargs)  # type: ignore[arg-type]

    wired_panel.runtime.service._append_audit = failing_append  # type: ignore[method-assign]

    status, _body, _headers = _request(
        wired_panel.base,
        f"/settings/users/{worker_id}/deactivate",
        method="POST",
        data={"_csrf_token": _cookie_value(jar, "sl_employee_csrf")},
        jar=jar,
    )
    assert status == 500

    verify_after = _fresh_repository(wired_panel.db)
    try:
        after = verify_after.get_account_by_id(worker_id)
        assert after is not None
        assert after.is_active is True
        assert after.deactivated_at is None
        events = verify_after.list_audit_events_for_account(worker_id, limit=100)
        assert not any(
            event.action == "auth.account_deactivated" and event.outcome == "success"
            for event in events
        )
    finally:
        verify_after.close()


def test_managed_runtime_concurrent_last_superadmin_protection(
    tmp_path: Path,
) -> None:
    db = tmp_path / "concurrent.db"
    setup = open_managed_employee_auth_runtime(
        db, now=lambda: datetime(2026, 8, 1, 10, 0, tzinfo=UTC)
    )
    setup.service.bootstrap_superadmin(
        username="super.admin",
        display_name="Super Admin",
        password="TempPassw0rd!",
    )
    login = setup.service.authenticate(username="super.admin", password="TempPassw0rd!")
    actor = setup.service.authenticate_session(login.session_token)
    setup.service.change_password(
        actor,
        current_password="TempPassw0rd!",
        new_password="ChangedTemp1!",
    )
    relogin = setup.service.authenticate(
        username="super.admin", password="ChangedTemp1!"
    )
    actor = setup.service.authenticate_session(relogin.session_token)
    backup = setup.service.create_account(
        actor,
        username="super.two",
        display_name="Super Two",
        password="SecondTemp1!",
        role="SUPERADMIN",
    )
    super_one_id = actor.account.id
    super_two_id = backup.id
    setup.close()

    barrier = threading.Barrier(2)
    results: list[tuple[str, str]] = []

    def attempt_demote(target_id: str) -> None:
        runtime = open_managed_employee_auth_runtime(
            db, now=lambda: datetime(2026, 8, 1, 10, 30, tzinfo=UTC)
        )
        login_result = runtime.service.authenticate(
            username="super.admin", password="ChangedTemp1!"
        )
        thread_actor = runtime.service.authenticate_session(login_result.session_token)
        barrier.wait(timeout=5)
        try:
            runtime.service.change_account_role(thread_actor, target_id, "ADMIN")
            results.append(("ok", target_id))
        except LastActiveSuperadminError:
            results.append(("blocked", target_id))
        finally:
            runtime.close()

    threads = [
        threading.Thread(target=attempt_demote, args=(super_one_id,)),
        threading.Thread(target=attempt_demote, args=(super_two_id,)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    verify = open_managed_employee_auth_runtime(db)
    try:
        assert verify.repository.count_active_superadmins() >= 1
    finally:
        verify.close()

    assert len(results) == 2
    assert {item[0] for item in results} == {"ok", "blocked"}


def test_create_account_is_always_active(wired_panel: WiredPanel) -> None:
    jar = _ready_superadmin_jar(wired_panel)
    worker_id = _create_worker(wired_panel, jar, username="worker.always.active")
    verify = _fresh_repository(wired_panel.db)
    try:
        account = verify.get_account_by_id(worker_id)
        assert account is not None
        assert account.is_active is True
    finally:
        verify.close()


def test_invalid_role_post_renders_safe_german_error(wired_panel: WiredPanel) -> None:
    jar = _ready_superadmin_jar(wired_panel)
    status, body, _headers = _request(
        wired_panel.base,
        "/settings/users",
        method="POST",
        data={
            "_csrf_token": _cookie_value(jar, "sl_employee_csrf"),
            "username": "bad.role.user",
            "display_name": "Bad Role User",
            "role": "NOT_A_ROLE",
            "temporary_password": "WorkerTemp1!",
        },
        jar=jar,
    )
    assert status == 400
    assert "Die ausgewählte Rolle ist nicht zulässig." in body
    assert "role must be one of" not in body
    assert 'value="WorkerTemp1!"' not in body

    verify = _fresh_repository(wired_panel.db)
    try:
        assert verify.get_account_by_username("bad.role.user") is None
    finally:
        verify.close()
