"""Production HTTP wiring tests for AUTH-2B account-management transactions."""

from __future__ import annotations

import json
import queue
import sqlite3
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
from catering_system.services.employee_auth_service import (
    EmployeeAuthService,
    LastActiveSuperadminError,
)
from catering_system.ui.employee_auth_api import create_employee_auth_server


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


def _seed_superadmin(db: Path) -> None:
    repo = SQLiteEmployeeAuthRepository(db)
    service = EmployeeAuthService(
        repo,
        now=lambda: datetime(2026, 8, 1, 10, 0, tzinfo=UTC),
    )
    service.bootstrap_superadmin(
        username="super.admin",
        display_name="Super Admin",
        password="TempPassw0rd!",
        metadata={"seed": "server-wiring"},
    )
    repo.close()


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


def _start_server(db: Path) -> tuple[HTTPServer, threading.Thread, str]:
    ready: queue.Queue[HTTPServer] = queue.Queue()

    def run() -> None:
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


def _stop_server(server: HTTPServer, thread: threading.Thread) -> None:
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def _runtime_repository(db: Path) -> SQLiteEmployeeAuthRepository:
    repository = SQLiteEmployeeAuthRepository(db)
    repository._conn.execute("PRAGMA busy_timeout = 2000")
    assert repository._manage_transactions is True
    return repository


def _create_worker_via_http(base: str, cookie: str, csrf: str, *, username: str) -> str:
    status, body, _headers = _request(
        f"{base}/auth/accounts",
        method="POST",
        headers={"Cookie": cookie, "X-CSRF-Token": csrf},
        body={
            "username": username,
            "display_name": "Worker Wiring",
            "role": "USER",
            "temporary_password": "WorkerTemp1!",
        },
    )
    assert status == 201
    return str(body["account"]["id"])


@pytest.fixture()
def wired_server(tmp_path: Path):
    db = tmp_path / "core.db"
    _seed_superadmin(db)
    server, thread, base = _start_server(db)
    yield db, server, base
    _stop_server(server, thread)


def test_runtime_repository_uses_managed_transactions(tmp_path: Path) -> None:
    db = tmp_path / "managed.db"
    repository = _runtime_repository(db)
    try:
        assert repository._manage_transactions is True
        assert not repository._conn.in_transaction
        with repository.immediate_transaction():
            assert repository._conn.in_transaction
        assert not repository._conn.in_transaction
    finally:
        repository.close()


def test_http_profile_update_rolls_back_when_success_audit_fails(
    wired_server: tuple[Path, HTTPServer, str],
) -> None:
    db, server, base = wired_server
    assert server.auth_repository._manage_transactions is True
    cookie, csrf = _login_ready(base, username="super.admin", password="TempPassw0rd!")
    worker_id = _create_worker_via_http(
        base, cookie, csrf, username="worker.http.rollback"
    )

    verify_before = _runtime_repository(db)
    try:
        before = verify_before.get_account_by_id(worker_id)
        assert before is not None
        assert before.display_name == "Worker Wiring"
    finally:
        verify_before.close()

    original_append = server.auth_service._append_audit

    def failing_append(**kwargs: object) -> None:
        if kwargs.get("action") == "auth.account_profile_updated":
            raise sqlite3.OperationalError("audit insert failed")
        original_append(**kwargs)  # type: ignore[arg-type]

    server.auth_service._append_audit = failing_append  # type: ignore[method-assign]

    status, body, _headers = _request(
        f"{base}/auth/accounts/{worker_id}",
        method="PATCH",
        headers={"Cookie": cookie, "X-CSRF-Token": csrf},
        body={"display_name": "Should Roll Back"},
    )
    assert status == 500
    assert body["error"] == "internal_error"

    verify_after = _runtime_repository(db)
    try:
        after = verify_after.get_account_by_id(worker_id)
        assert after is not None
        assert after.display_name == "Worker Wiring"
        events = verify_after.list_audit_events_for_account(worker_id, limit=100)
        assert not any(
            event.action == "auth.account_profile_updated" for event in events
        )
    finally:
        verify_after.close()


def test_http_password_reset_rolls_back_when_success_audit_fails(
    wired_server: tuple[Path, HTTPServer, str],
) -> None:
    db, server, base = wired_server
    cookie, csrf = _login_ready(base, username="super.admin", password="TempPassw0rd!")
    worker_id = _create_worker_via_http(
        base, cookie, csrf, username="worker.http.reset"
    )

    worker_login = _request(
        f"{base}/auth/login",
        method="POST",
        body={"username": "worker.http.reset", "password": "WorkerTemp1!"},
    )
    assert worker_login[0] == 200

    verify_before = _runtime_repository(db)
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

    original_append = server.auth_service._append_audit

    def failing_append(**kwargs: object) -> None:
        if kwargs.get("action") == "auth.password_reset":
            raise sqlite3.OperationalError("audit insert failed")
        original_append(**kwargs)  # type: ignore[arg-type]

    server.auth_service._append_audit = failing_append  # type: ignore[method-assign]

    status, body, _headers = _request(
        f"{base}/auth/accounts/{worker_id}/reset-password",
        method="POST",
        headers={"Cookie": cookie, "X-CSRF-Token": csrf},
        body={"temporary_password": "ResetTemp1!"},
    )
    assert status == 500
    assert body["error"] == "internal_error"

    verify_after = _runtime_repository(db)
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


def test_runtime_repository_concurrent_last_superadmin_protection(
    tmp_path: Path,
) -> None:
    db = tmp_path / "concurrent.db"
    setup_repo = _runtime_repository(db)
    setup_service = EmployeeAuthService(
        setup_repo,
        now=lambda: datetime(2026, 8, 1, 10, 0, tzinfo=UTC),
    )
    setup_service.bootstrap_superadmin(
        username="super.admin",
        display_name="Super Admin",
        password="TempPassw0rd!",
    )
    login = setup_service.authenticate(username="super.admin", password="TempPassw0rd!")
    actor = setup_service.authenticate_session(login.session_token)
    setup_service.change_password(
        actor,
        current_password="TempPassw0rd!",
        new_password="ChangedTemp1!",
    )
    relogin = setup_service.authenticate(
        username="super.admin", password="ChangedTemp1!"
    )
    actor = setup_service.authenticate_session(relogin.session_token)
    backup = setup_service.create_account(
        actor,
        username="super.two",
        display_name="Super Two",
        password="SecondTemp1!",
        role="SUPERADMIN",
    )
    super_one_id = actor.account.id
    super_two_id = backup.id
    setup_repo.close()

    barrier = threading.Barrier(2)
    results: list[tuple[str, str]] = []

    def attempt_demote(target_id: str) -> None:
        repository = _runtime_repository(db)
        service = EmployeeAuthService(
            repository,
            now=lambda: datetime(2026, 8, 1, 10, 30, tzinfo=UTC),
        )
        login_result = service.authenticate(
            username="super.admin", password="ChangedTemp1!"
        )
        thread_actor = service.authenticate_session(login_result.session_token)
        barrier.wait(timeout=5)
        try:
            service.change_account_role(thread_actor, target_id, "ADMIN")
            results.append(("ok", target_id))
        except LastActiveSuperadminError:
            results.append(("blocked", target_id))
        finally:
            repository.close()

    threads = [
        threading.Thread(target=attempt_demote, args=(super_one_id,)),
        threading.Thread(target=attempt_demote, args=(super_two_id,)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    verify_repo = _runtime_repository(db)
    try:
        assert verify_repo.count_active_superadmins() >= 1
    finally:
        verify_repo.close()

    assert len(results) == 2
    assert {item[0] for item in results} == {"ok", "blocked"}
