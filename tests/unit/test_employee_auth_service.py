from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from catering_system.domain.employee_auth import (
    effective_permissions,
    normalize_username,
    role_ceiling,
    validate_display_name,
)
from catering_system.repositories.sqlite_employee_auth_repository import (
    SQLiteEmployeeAuthRepository,
)
from catering_system.services.employee_auth_service import (
    AuthenticationError,
    AuthorizationError,
    EmployeeAuthService,
    LastActiveSuperadminError,
    verify_password,
)


class Clock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def now(self) -> datetime:
        return self.value


@pytest.fixture()
def auth(tmp_path: Path):
    clock = Clock(datetime(2026, 8, 1, 9, 0, tzinfo=UTC))
    repo = SQLiteEmployeeAuthRepository(tmp_path / "core.db")
    service = EmployeeAuthService(
        repo,
        now=clock.now,
        service_tokens={"office-api": "svc-office-token"},
    )
    return service, repo, clock


def _bootstrap(auth):
    service, repo, _clock = auth
    account = service.bootstrap_superadmin(
        username="Viktor.Admin",
        display_name="Viktor Johanson",
        password="TempPassw0rd!",
        metadata={"seed": "test"},
    )
    return service, repo, account


def _login_superadmin(auth):
    service, repo, _account = _bootstrap(auth)
    result = service.authenticate(username="viktor.admin", password="TempPassw0rd!")
    employee = service.authenticate_session(result.session_token)
    return service, repo, result, employee


def _login_superadmin_ready(auth):
    service, repo, result, employee = _login_superadmin(auth)
    service.change_password(
        employee,
        current_password="TempPassw0rd!",
        new_password="ChangedTemp1!",
    )
    relogin = service.authenticate(username="viktor.admin", password="ChangedTemp1!")
    ready_employee = service.authenticate_session(relogin.session_token)
    return service, repo, relogin, ready_employee


def test_username_normalization_and_display_name_validation() -> None:
    assert normalize_username("  Viktor.Admin  ") == "viktor.admin"
    assert validate_display_name("  Viktor Johanson ") == "Viktor Johanson"
    with pytest.raises(ValueError, match="username"):
        normalize_username("AB")
    with pytest.raises(ValueError, match="display_name"):
        validate_display_name("   ")


def test_password_hashing_and_verification(auth) -> None:
    service, repo, account = _bootstrap(auth)
    stored = repo.get_account_by_id(account.id)
    assert stored is not None
    assert stored.password_hash != "TempPassw0rd!"
    assert verify_password("TempPassw0rd!", stored.password_hash) is True
    assert verify_password("wrong-password", stored.password_hash) is False
    assert verify_password("TempPassw0rd!", "scrypt$bad") is False


def test_username_uniqueness_is_case_insensitive(auth) -> None:
    service, repo, _result, employee = _login_superadmin_ready(auth)
    service.create_account(
        employee,
        username="worker.one",
        display_name="Worker One",
        password="AnotherTemp1!",
        role="USER",
    )
    with pytest.raises(sqlite3.IntegrityError):
        service.create_account(
            employee,
            username="Worker.One",
            display_name="Worker Duplicate",
            password="AnotherTemp1!",
            role="USER",
        )


def test_role_ceilings_and_viewer_read_only_enforcement() -> None:
    assert "offers.prepare" in role_ceiling("ADMIN")
    assert "users.roles.assign" not in role_ceiling("USER")
    assert "offers.prepare" not in role_ceiling("VIEWER")
    assert all(permission.endswith(".view") for permission in role_ceiling("VIEWER"))


def test_effective_permissions_intersect_role_ceiling() -> None:
    explicit = {"offers.prepare", "offers.view", "settings.edit"}
    assert effective_permissions("USER", explicit) == frozenset(
        {"offers.prepare", "offers.view"}
    )
    assert effective_permissions("VIEWER", explicit) == frozenset({"offers.view"})


def test_session_creation_validation_expiry_and_revocation(auth) -> None:
    service, _repo, _account = _bootstrap(auth)
    result = service.authenticate(username="viktor.admin", password="TempPassw0rd!")
    employee = service.authenticate_session(result.session_token)
    assert employee.account.username == "viktor.admin"
    clock = auth[2]
    clock.value = clock.value + timedelta(hours=13)
    with pytest.raises(AuthenticationError, match="expired"):
        service.authenticate_session(result.session_token)


def test_inactive_account_login_is_rejected(auth) -> None:
    service, _repo, _result, employee = _login_superadmin_ready(auth)
    target = service.create_account(
        employee,
        username="worker.inactive",
        display_name="Worker Inactive",
        password="AnotherTemp1!",
        role="USER",
    )
    service.deactivate_account(employee, target.id)
    with pytest.raises(AuthenticationError, match="inactive"):
        service.authenticate(username="worker.inactive", password="AnotherTemp1!")


def test_auth_version_mismatch_rejects_session(auth) -> None:
    service, _repo, result, employee = _login_superadmin(auth)
    service.change_password(
        employee,
        current_password="TempPassw0rd!",
        new_password="ChangedTemp1!",
    )
    with pytest.raises(AuthenticationError, match="revoked|invalidated"):
        service.authenticate_session(result.session_token)


def test_must_change_password_blocks_application_permissions_until_changed(
    auth,
) -> None:
    service, _repo, _account = _bootstrap(auth)
    result = service.authenticate(username="viktor.admin", password="TempPassw0rd!")
    employee = service.authenticate_session(result.session_token)
    assert employee.account.must_change_password is True
    assert employee.application_access_allowed is False
    assert employee.effective_permissions == frozenset()
    introspection = service.introspect(
        session_token=result.session_token,
        bearer_token=None,
    )
    assert introspection.authenticated is True
    assert introspection.application_access_allowed is False
    assert introspection.effective_permissions == frozenset()
    with pytest.raises(AuthorizationError, match="password change required"):
        service.create_account(
            employee,
            username="blocked.user",
            display_name="Blocked User",
            password="BlockedTemp1!",
            role="USER",
        )

    updated = service.change_password(
        employee,
        current_password="TempPassw0rd!",
        new_password="ChangedTemp1!",
    )
    assert updated.must_change_password is False
    with pytest.raises(AuthenticationError):
        service.authenticate_session(result.session_token)

    relogin = service.authenticate(username="viktor.admin", password="ChangedTemp1!")
    assert relogin.application_access_allowed is True
    assert "settings.edit" in relogin.effective_permissions


def test_deactivation_and_password_change_invalidate_sessions(auth) -> None:
    service, repo, result, employee = _login_superadmin_ready(auth)
    target = service.create_account(
        employee,
        username="worker.two",
        display_name="Worker Two",
        password="AnotherTemp1!",
        role="USER",
    )
    worker_login = service.authenticate(username="worker.two", password="AnotherTemp1!")
    service.authenticate_session(worker_login.session_token)
    service.deactivate_account(employee, target.id)
    with pytest.raises(AuthenticationError, match="revoked"):
        service.authenticate_session(worker_login.session_token)

    service.reactivate_account(employee, target.id)
    worker_login2 = service.authenticate(
        username="worker.two", password="AnotherTemp1!"
    )
    worker2 = service.authenticate_session(worker_login2.session_token)
    service.change_password(
        worker2,
        current_password="AnotherTemp1!",
        new_password="ChangedTemp1!",
    )
    with pytest.raises(AuthenticationError):
        service.authenticate_session(worker_login2.session_token)
    relogin = service.authenticate(username="worker.two", password="ChangedTemp1!")
    assert relogin.account.must_change_password is False


def test_last_active_superadmin_guard(auth) -> None:
    service, _repo, _result, employee = _login_superadmin_ready(auth)
    with pytest.raises(LastActiveSuperadminError):
        service.deactivate_account(employee, employee.account.id)
    with pytest.raises(LastActiveSuperadminError):
        service.change_account_role(employee, employee.account.id, "ADMIN")


def test_bootstrap_and_recovery_reset(auth) -> None:
    service, repo, account = _bootstrap(auth)
    assert repo.count_accounts() == 1
    reset = service.reset_password(
        actor=None,
        target_username=account.username,
        temporary_password="RecoveredTemp1!",
        recovery=True,
    )
    assert reset.must_change_password is True
    login = service.authenticate(username=account.username, password="RecoveredTemp1!")
    assert login.account.must_change_password is True


def test_admin_may_grant_only_within_own_effective_permissions(auth) -> None:
    service, _repo, _result, superadmin = _login_superadmin_ready(auth)
    admin = service.create_account(
        superadmin,
        username="team.admin",
        display_name="Team Admin",
        password="AdminTemp1!",
        role="ADMIN",
        explicit_permissions={"users.view", "users.create", "users.permissions.assign"},
    )
    worker = service.create_account(
        superadmin,
        username="worker.three",
        display_name="Worker Three",
        password="WorkerTemp1!",
        role="USER",
    )
    admin_login = service.authenticate(username=admin.username, password="AdminTemp1!")
    admin_employee = service.authenticate_session(admin_login.session_token)
    with pytest.raises(AuthorizationError):
        service.set_account_permissions(
            admin_employee,
            worker.id,
            {"offers.prepare"},
        )


def test_introspection_distinguishes_session_service_and_public(auth) -> None:
    service, _repo, _account = _bootstrap(auth)
    result = service.authenticate(username="viktor.admin", password="TempPassw0rd!")
    session = service.introspect(session_token=result.session_token, bearer_token=None)
    assert session.kind == "employee_session"
    assert session.authenticated is True
    service_token = service.introspect(
        session_token=None, bearer_token="svc-office-token"
    )
    assert service_token.kind == "service_token"
    public = service.introspect(session_token=None, bearer_token="wrong")
    assert public.kind == "public"
    assert public.authenticated is False


def test_audit_redaction_and_append_only(auth) -> None:
    service, repo, account = _bootstrap(auth)
    service.reset_password(
        actor=None,
        target_username=account.username,
        temporary_password="RecoveredTemp1!",
        recovery=True,
    )
    events = repo.list_audit_events()
    assert events
    assert all("RecoveredTemp1!" not in event.metadata_json for event in events)
    assert all(
        "password" not in json.loads(event.metadata_json).get("temporary_password", "")
        for event in events
    )
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        repo._conn.execute(  # noqa: SLF001
            "DELETE FROM security_audit_events WHERE event_id = ?",
            (events[0].event_id,),
        )
