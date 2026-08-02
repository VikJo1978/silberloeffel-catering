"""Office Panel business authorization helpers (AUTH-2D1).

Centralizes permission checks for employee sessions while preserving the
migration/basic legacy rollback path. Settings/users routes keep their
separate employee-only actor rules from AUTH-2C.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Protocol

from catering_system.domain.employee_auth import PERMISSION_SET, AuthenticatedEmployee

if TYPE_CHECKING:
    from catering_system.ui.office_panel_http import OfficePanelRequestAuth


class BusinessAccessDenied(Exception):
    """Raised when an employee session lacks a required business permission."""


class BusinessAuthRequest(Protocol):
    kind: Literal["basic", "employee"]
    legacy_shared_access: bool
    employee: AuthenticatedEmployee | None


def can_access(
    auth: BusinessAuthRequest | "OfficePanelRequestAuth" | None,
    permission_code: str,
) -> bool:
    """Return whether ``permission_code`` is allowed for this request principal."""
    if permission_code not in PERMISSION_SET:
        return False
    if auth is None:
        return False
    if auth.legacy_shared_access:
        return True
    if auth.kind != "employee" or auth.employee is None:
        return False
    if not auth.employee.application_access_allowed:
        return False
    return permission_code in auth.employee.effective_permissions


def can_access_all(
    auth: BusinessAuthRequest | "OfficePanelRequestAuth" | None,
    permission_codes: tuple[str, ...],
) -> bool:
    return all(can_access(auth, code) for code in permission_codes)


def require_business_permission(
    auth: BusinessAuthRequest | "OfficePanelRequestAuth" | None,
    permission_code: str,
) -> None:
    if not can_access(auth, permission_code):
        raise BusinessAccessDenied()


def require_all_business_permissions(
    auth: BusinessAuthRequest | "OfficePanelRequestAuth" | None,
    permission_codes: tuple[str, ...],
) -> None:
    for permission_code in permission_codes:
        require_business_permission(auth, permission_code)


def require_business_permission_post(
    auth: BusinessAuthRequest | "OfficePanelRequestAuth" | None,
    permission_code: str,
) -> None:
    """POST alias — same employee/Basic semantics as GET (AUTH-2D2)."""
    require_business_permission(auth, permission_code)


def require_all_business_permissions_post(
    auth: BusinessAuthRequest | "OfficePanelRequestAuth" | None,
    permission_codes: tuple[str, ...],
) -> None:
    require_all_business_permissions(auth, permission_codes)
