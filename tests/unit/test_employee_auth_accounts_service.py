from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from catering_system.services.employee_auth_service import (
    AccountConflictError,
    AuthorizationError,
    EmployeeAuthService,
    LastActiveSuperadminError,
)


class Clock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def now(self) -> datetime:
        return self.value


@pytest.fixture()
def auth(tmp_path: Path):
    from catering_system.repositories.sqlite_employee_auth_repository import (
        SQLiteEmployeeAuthRepository,
    )

    clock = Clock(datetime(2026, 8, 1, 9, 0, tzinfo=UTC))
    repo = SQLiteEmployeeAuthRepository(tmp_path / "core.db")
    service = EmployeeAuthService(repo, now=clock.now)
    return service, repo, clock


def _bootstrap(auth):
    service, repo, _clock = auth
    account = service.bootstrap_superadmin(
        username="super.admin",
        display_name="Super Admin",
        password="TempPassw0rd!",
        metadata={"seed": "accounts"},
    )
    return service, repo, account


def _ready_superadmin(auth):
    service, repo, _account = _bootstrap(auth)
    login = service.authenticate(username="super.admin", password="TempPassw0rd!")
    employee = service.authenticate_session(login.session_token)
    service.change_password(
        employee,
        current_password="TempPassw0rd!",
        new_password="ChangedTemp1!",
    )
    relogin = service.authenticate(username="super.admin", password="ChangedTemp1!")
    return service, repo, service.authenticate_session(relogin.session_token)


def _ready_admin(auth, superadmin):
    service = auth[0]
    admin = service.create_account(
        superadmin,
        username="team.admin",
        display_name="Team Admin",
        password="AdminTemp1!",
        role="ADMIN",
    )
    login = service.authenticate(username=admin.username, password="AdminTemp1!")
    employee = service.authenticate_session(login.session_token)
    service.change_password(
        employee,
        current_password="AdminTemp1!",
        new_password="AdminChanged1!",
    )
    relogin = service.authenticate(username=admin.username, password="AdminChanged1!")
    return service.authenticate_session(relogin.session_token)


def test_superadmin_lists_all_accounts(auth) -> None:
    service, _repo, superadmin = _ready_superadmin(auth)
    service.create_account(
        superadmin,
        username="worker.one",
        display_name="Worker One",
        password="WorkerTemp1!",
        role="USER",
    )
    accounts = service.list_accounts(superadmin)
    assert {item.username for item in accounts} == {"super.admin", "worker.one"}


def test_admin_lists_all_but_cannot_mutate_admin_or_superadmin(auth) -> None:
    service, _repo, superadmin = _ready_superadmin(auth)
    admin_employee = _ready_admin(auth, superadmin)
    worker = service.create_account(
        superadmin,
        username="worker.viewer",
        display_name="Worker Viewer",
        password="ViewerTemp1!",
        role="VIEWER",
        explicit_permissions={"inquiries.view"},
    )
    listed = service.list_accounts(admin_employee)
    assert {item.username for item in listed} == {
        "super.admin",
        "team.admin",
        "worker.viewer",
    }
    assert next(item for item in listed if item.username == "super.admin").read_only
    with pytest.raises(AuthorizationError):
        service.deactivate_account(admin_employee, superadmin.account.id)
    with pytest.raises(AuthorizationError):
        service.update_account_profile(
            admin_employee, superadmin.account.id, display_name="Blocked"
        )
    detail = service.update_account_profile(
        admin_employee, worker.id, display_name="Updated Viewer"
    )
    assert detail.display_name == "Updated Viewer"


def test_user_and_viewer_denied_account_management(auth) -> None:
    service, _repo, superadmin = _ready_superadmin(auth)
    user = service.create_account(
        superadmin,
        username="worker.user",
        display_name="Worker User",
        password="WorkerTemp1!",
        role="USER",
    )
    login = service.authenticate(username=user.username, password="WorkerTemp1!")
    employee = service.authenticate_session(login.session_token)
    service.change_password(
        employee,
        current_password="WorkerTemp1!",
        new_password="WorkerChanged1!",
    )
    relogin = service.authenticate(username=user.username, password="WorkerChanged1!")
    ready = service.authenticate_session(relogin.session_token)
    with pytest.raises(AuthorizationError):
        service.list_accounts(ready)


def test_create_user_and_viewer_with_read_only_grants(auth) -> None:
    service, _repo, superadmin = _ready_superadmin(auth)
    user = service.create_account(
        superadmin,
        username="worker.new",
        display_name="Worker New",
        password="WorkerTemp1!",
        role="USER",
    )
    viewer = service.create_account(
        superadmin,
        username="viewer.new",
        display_name="Viewer New",
        password="ViewerTemp1!",
        role="VIEWER",
        explicit_permissions={"inquiries.view", "offers.view"},
    )
    detail = service.get_account(superadmin, viewer.id)
    assert detail.effective_permissions == frozenset({"inquiries.view", "offers.view"})
    assert user.must_change_password is True


def test_admin_cannot_create_admin_and_superadmin_can(auth) -> None:
    service, _repo, superadmin = _ready_superadmin(auth)
    admin_employee = _ready_admin(auth, superadmin)
    with pytest.raises(AuthorizationError):
        service.create_account(
            admin_employee,
            username="blocked.admin",
            display_name="Blocked Admin",
            password="BlockedTemp1!",
            role="ADMIN",
        )
    created = service.create_account(
        superadmin,
        username="second.admin",
        display_name="Second Admin",
        password="SecondAdmin1!",
        role="ADMIN",
    )
    assert created.role == "ADMIN"


def test_case_insensitive_username_conflict(auth) -> None:
    service, _repo, superadmin = _ready_superadmin(auth)
    service.create_account(
        superadmin,
        username="worker.case",
        display_name="Worker Case",
        password="WorkerTemp1!",
        role="USER",
    )
    with pytest.raises(AccountConflictError):
        service.create_account(
            superadmin,
            username="Worker.Case",
            display_name="Worker Duplicate",
            password="WorkerTemp1!",
            role="USER",
        )


def test_profile_update_preserves_immutable_account_id(auth) -> None:
    service, _repo, superadmin = _ready_superadmin(auth)
    worker = service.create_account(
        superadmin,
        username="worker.profile",
        display_name="Worker Profile",
        password="WorkerTemp1!",
        role="USER",
    )
    detail = service.update_account_profile(
        superadmin,
        worker.id,
        username="worker.renamed",
        display_name="Worker Renamed",
        email="worker@example.com",
    )
    assert detail.id == worker.id
    assert detail.username == "worker.renamed"


def test_role_change_applies_immediately_and_unknown_role_rejected(auth) -> None:
    service, _repo, superadmin = _ready_superadmin(auth)
    worker = service.create_account(
        superadmin,
        username="worker.role",
        display_name="Worker Role",
        password="WorkerTemp1!",
        role="USER",
        explicit_permissions={"offers.prepare", "offers.view"},
    )
    service.change_account_role(superadmin, worker.id, "VIEWER")
    detail = service.get_account(superadmin, worker.id)
    assert detail.role == "VIEWER"
    assert detail.effective_permissions == frozenset({"offers.view"})
    with pytest.raises(ValueError, match="role must be one of"):
        service.change_account_role(superadmin, worker.id, "MYSTERY")


def test_permission_replacement_is_atomic_and_unknown_permission_rejected(auth) -> None:
    service, _repo, superadmin = _ready_superadmin(auth)
    worker = service.create_account(
        superadmin,
        username="worker.perms",
        display_name="Worker Perms",
        password="WorkerTemp1!",
        role="USER",
    )
    with pytest.raises(ValueError, match="permission_code"):
        service.set_account_permissions(
            superadmin, worker.id, {"offers.prepare", "not.real"}
        )
    service.set_account_permissions(
        superadmin, worker.id, {"offers.prepare", "offers.view"}
    )
    detail = service.get_account(superadmin, worker.id)
    assert detail.effective_permissions == frozenset({"offers.prepare", "offers.view"})


def test_viewer_write_grant_rejected(auth) -> None:
    service, _repo, superadmin = _ready_superadmin(auth)
    viewer = service.create_account(
        superadmin,
        username="viewer.write",
        display_name="Viewer Write",
        password="ViewerTemp1!",
        role="VIEWER",
    )
    with pytest.raises(ValueError, match="permissions exceed VIEWER ceiling"):
        service.set_account_permissions(
            superadmin, viewer.id, {"offers.view", "offers.prepare"}
        )


def test_admin_cannot_grant_permission_not_owned(auth) -> None:
    service, _repo, superadmin = _ready_superadmin(auth)
    limited_admin = service.create_account(
        superadmin,
        username="limited.admin",
        display_name="Limited Admin",
        password="LimitedAdmin1!",
        role="ADMIN",
        explicit_permissions={
            "users.view",
            "users.permissions.assign",
            "inquiries.view",
        },
    )
    login = service.authenticate(
        username=limited_admin.username, password="LimitedAdmin1!"
    )
    admin_employee = service.authenticate_session(login.session_token)
    service.change_password(
        admin_employee,
        current_password="LimitedAdmin1!",
        new_password="LimitedChanged1!",
    )
    relogin = service.authenticate(
        username=limited_admin.username, password="LimitedChanged1!"
    )
    admin_employee = service.authenticate_session(relogin.session_token)
    worker = service.create_account(
        superadmin,
        username="worker.grant",
        display_name="Worker Grant",
        password="WorkerTemp1!",
        role="USER",
    )
    with pytest.raises(AuthorizationError):
        service.set_account_permissions(admin_employee, worker.id, {"offers.prepare"})


def test_deactivation_revokes_sessions_and_reactivation_does_not_create_session(
    auth,
) -> None:
    service, repo, superadmin = _ready_superadmin(auth)
    worker = service.create_account(
        superadmin,
        username="worker.lifecycle",
        display_name="Worker Lifecycle",
        password="WorkerTemp1!",
        role="USER",
    )
    login = service.authenticate(username=worker.username, password="WorkerTemp1!")
    service.deactivate_account(superadmin, worker.id)
    session = repo.get_session_by_token_hash(login.session.token_hash)
    assert session is not None
    assert session.revoked_at is not None
    service.reactivate_account(superadmin, worker.id)
    assert repo.get_session_by_token_hash(login.session.token_hash) is not None


def test_reset_password_sets_must_change_password_and_revokes_sessions(auth) -> None:
    service, repo, superadmin = _ready_superadmin(auth)
    worker = service.create_account(
        superadmin,
        username="worker.reset",
        display_name="Worker Reset",
        password="WorkerTemp1!",
        role="USER",
    )
    login = service.authenticate(username=worker.username, password="WorkerTemp1!")
    result = service.reset_account_password(
        superadmin, worker.id, temporary_password="ResetTemp1!"
    )
    assert result.temporary_password is None
    updated = service.get_account(superadmin, worker.id)
    assert updated.must_change_password is True
    session = repo.get_session_by_token_hash(login.session.token_hash)
    assert session is not None
    assert session.revoked_at is not None


def test_plaintext_password_absent_from_audit_and_generated_reset(auth) -> None:
    service, repo, superadmin = _ready_superadmin(auth)
    worker = service.create_account(
        superadmin,
        username="worker.audit",
        display_name="Worker Audit",
        password="WorkerTemp1!",
        role="USER",
    )
    result = service.reset_account_password(superadmin, worker.id)
    assert result.temporary_password is not None
    events = repo.list_audit_events_for_account(worker.id)
    assert events
    for event in events:
        assert result.temporary_password not in event.metadata_json
        assert "WorkerTemp1!" not in event.metadata_json


def test_last_active_superadmin_cannot_be_deactivated_or_demoted(auth) -> None:
    service, _repo, superadmin = _ready_superadmin(auth)
    with pytest.raises(LastActiveSuperadminError):
        service.deactivate_account(superadmin, superadmin.account.id)
    with pytest.raises(LastActiveSuperadminError):
        service.change_account_role(superadmin, superadmin.account.id, "ADMIN")


def test_last_active_superadmin_guard_allows_one_demotion_then_blocks_second(
    auth,
) -> None:
    service, _repo, superadmin = _ready_superadmin(auth)
    backup = service.create_account(
        superadmin,
        username="super.two",
        display_name="Super Two",
        password="SecondTemp1!",
        role="SUPERADMIN",
    )
    service.change_account_role(superadmin, backup.id, "ADMIN")
    with pytest.raises(LastActiveSuperadminError):
        service.change_account_role(superadmin, superadmin.account.id, "ADMIN")


def test_account_specific_audit_listing_is_permission_protected(auth) -> None:
    service, _repo, superadmin = _ready_superadmin(auth)
    worker = service.create_account(
        superadmin,
        username="worker.auditlist",
        display_name="Worker Audit List",
        password="WorkerTemp1!",
        role="USER",
    )
    service.deactivate_account(superadmin, worker.id)
    events = service.list_account_audit_events(superadmin, worker.id)
    assert events
    assert all(event.target_id == worker.id for event in events)
    admin_employee = _ready_admin(auth, superadmin)
    with pytest.raises(AuthorizationError):
        service.list_account_audit_events(admin_employee, worker.id)
