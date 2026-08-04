"""Office API employee-session introspection response contract (AUTH-2E1)."""

from __future__ import annotations

from dataclasses import dataclass

from catering_system.domain.employee_auth import AuthenticatedEmployee, EmployeeRole


@dataclass(frozen=True)
class EmployeeIntrospectionPrincipal:
    account_id: str
    username: str
    display_name: str
    role: EmployeeRole
    effective_permissions: tuple[str, ...]

    def to_json(self) -> dict[str, object]:
        return {
            "account_id": self.account_id,
            "username": self.username,
            "display_name": self.display_name,
            "role": self.role,
            "effective_permissions": list(self.effective_permissions),
        }


@dataclass(frozen=True)
class EmployeeIntrospectionResponse:
    authenticated: bool
    application_access_allowed: bool
    principal: EmployeeIntrospectionPrincipal | None

    def to_json(self) -> dict[str, object]:
        return {
            "authenticated": self.authenticated,
            "application_access_allowed": self.application_access_allowed,
            "principal": self.principal.to_json()
            if self.principal is not None
            else None,
        }


def employee_introspection_from_session(
    employee: AuthenticatedEmployee | None,
) -> EmployeeIntrospectionResponse:
    if employee is None:
        return EmployeeIntrospectionResponse(
            authenticated=False,
            application_access_allowed=False,
            principal=None,
        )
    permissions: tuple[str, ...] = ()
    if employee.application_access_allowed:
        permissions = tuple(sorted(employee.effective_permissions))
    return EmployeeIntrospectionResponse(
        authenticated=True,
        application_access_allowed=employee.application_access_allowed,
        principal=EmployeeIntrospectionPrincipal(
            account_id=employee.account.id,
            username=employee.account.username,
            display_name=employee.account.display_name,
            role=employee.account.role,
            effective_permissions=permissions,
        ),
    )
