from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pytest

from catering_system.domain.employee_auth import AuthenticatedEmployee
from catering_system.ui.office_panel_authz import (
    BusinessAccessDenied,
    can_access,
    can_access_all,
    require_all_business_permissions,
    require_all_business_permissions_post,
    require_business_permission,
    require_business_permission_post,
)


@dataclass(frozen=True)
class _AuthStub:
    kind: Literal["basic", "employee"]
    legacy_shared_access: bool
    employee: AuthenticatedEmployee | None = None


def test_unknown_permission_code_fails_closed() -> None:
    auth = _AuthStub(kind="employee", legacy_shared_access=False)
    assert can_access(auth, "not.a.real.permission") is False
    with pytest.raises(BusinessAccessDenied):
        require_business_permission(auth, "not.a.real.permission")


def test_legacy_basic_passes_without_employee_permissions() -> None:
    auth = _AuthStub(kind="basic", legacy_shared_access=True, employee=None)
    assert can_access(auth, "orders.view") is True
    require_business_permission(auth, "orders.view")


def test_employee_requires_effective_permission() -> None:
    from catering_system.domain.employee_auth import EmployeeAccount, EmployeeSession
    from datetime import UTC, datetime

    account = EmployeeAccount(
        id="acc-1",
        username="worker",
        email=None,
        display_name="Worker",
        password_hash="hash",
        role="USER",
        is_active=True,
        must_change_password=False,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        deactivated_at=None,
        last_login_at=None,
        auth_version=1,
    )
    session = EmployeeSession(
        id="sess-1",
        account_id="acc-1",
        token_hash="t",
        csrf_token_hash="c",
        created_at=datetime.now(UTC),
        last_seen_at=datetime.now(UTC),
        expires_at=datetime.now(UTC),
        revoked_at=None,
        revoked_reason=None,
        auth_version=1,
    )
    employee = AuthenticatedEmployee(
        account=account,
        session=session,
        application_access_allowed=True,
        effective_permissions=frozenset({"inquiries.view"}),
    )
    auth = _AuthStub(kind="employee", legacy_shared_access=False, employee=employee)
    assert can_access(auth, "inquiries.view") is True
    assert can_access(auth, "orders.view") is False
    assert can_access_all(auth, ("inquiries.view", "orders.view")) is False
    with pytest.raises(BusinessAccessDenied):
        require_all_business_permissions(auth, ("inquiries.view", "orders.view"))


def test_require_business_permission_post_matches_get_alias() -> None:
    from catering_system.domain.employee_auth import EmployeeAccount, EmployeeSession
    from datetime import UTC, datetime

    account = EmployeeAccount(
        id="acc-post",
        username="worker",
        email=None,
        display_name="Worker",
        password_hash="hash",
        role="USER",
        is_active=True,
        must_change_password=False,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        deactivated_at=None,
        last_login_at=None,
        auth_version=1,
    )
    session = EmployeeSession(
        id="sess-post",
        account_id="acc-post",
        token_hash="t",
        csrf_token_hash="c",
        created_at=datetime.now(UTC),
        last_seen_at=datetime.now(UTC),
        expires_at=datetime.now(UTC),
        revoked_at=None,
        revoked_reason=None,
        auth_version=1,
    )
    employee = AuthenticatedEmployee(
        account=account,
        session=session,
        application_access_allowed=True,
        effective_permissions=frozenset({"inquiries.view"}),
    )
    auth = _AuthStub(kind="employee", legacy_shared_access=False, employee=employee)

    require_business_permission_post(auth, "inquiries.view")
    with pytest.raises(BusinessAccessDenied):
        require_business_permission_post(auth, "orders.view")


def test_require_all_business_permissions_post_matches_get_alias() -> None:
    from catering_system.domain.employee_auth import EmployeeAccount, EmployeeSession
    from datetime import UTC, datetime

    account = EmployeeAccount(
        id="acc-all-post",
        username="worker",
        email=None,
        display_name="Worker",
        password_hash="hash",
        role="USER",
        is_active=True,
        must_change_password=False,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        deactivated_at=None,
        last_login_at=None,
        auth_version=1,
    )
    session = EmployeeSession(
        id="sess-all-post",
        account_id="acc-all-post",
        token_hash="t",
        csrf_token_hash="c",
        created_at=datetime.now(UTC),
        last_seen_at=datetime.now(UTC),
        expires_at=datetime.now(UTC),
        revoked_at=None,
        revoked_reason=None,
        auth_version=1,
    )
    employee = AuthenticatedEmployee(
        account=account,
        session=session,
        application_access_allowed=True,
        effective_permissions=frozenset({"inquiries.view", "customers.edit"}),
    )
    auth = _AuthStub(kind="employee", legacy_shared_access=False, employee=employee)

    require_all_business_permissions_post(auth, ("inquiries.view", "customers.edit"))
    with pytest.raises(BusinessAccessDenied):
        require_all_business_permissions_post(auth, ("inquiries.view", "orders.view"))


def test_post_aliases_preserve_legacy_basic_fallback() -> None:
    auth = _AuthStub(kind="basic", legacy_shared_access=True, employee=None)
    require_business_permission_post(auth, "inquiries.create")
    require_all_business_permissions_post(
        auth, ("offers.view", "orders.version.create")
    )
