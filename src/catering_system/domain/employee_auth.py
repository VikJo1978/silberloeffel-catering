"""Employee authentication and authorization foundation for AUTH_RBAC_V1."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, cast

EmployeeRole = Literal["SUPERADMIN", "ADMIN", "USER", "VIEWER"]
ActorType = Literal["employee", "service", "system", "public"]
AuditOutcome = Literal["success", "failure"]

_ROLE_VALUES: tuple[EmployeeRole, ...] = ("SUPERADMIN", "ADMIN", "USER", "VIEWER")
ROLE_SET: frozenset[str] = frozenset(_ROLE_VALUES)

PERMISSION_REGISTRY: tuple[str, ...] = (
    "inquiries.view",
    "inquiries.create",
    "inquiries.edit",
    "inquiries.verify",
    "customers.view",
    "customers.edit",
    "offers.view",
    "offers.prepare",
    "offers.version.create",
    "offers.pdf.generate",
    "offers.send",
    "offers.status.change",
    "offers.timing.acknowledge",
    "orders.view",
    "orders.version.create",
    "orders.print.confirm",
    "orders.effective.set",
    "orders.ready.release",
    "orders.pause",
    "orders.cancel",
    "catalog.view",
    "catalog.edit",
    "prices.view",
    "prices.edit",
    "calendar.view",
    "queue.view",
    "documents.view",
    "users.view",
    "users.create",
    "users.edit",
    "users.deactivate",
    "users.reactivate",
    "users.password.reset",
    "users.permissions.assign",
    "users.roles.assign",
    "audit.view",
    "settings.view",
    "settings.edit",
)
PERMISSION_SET: frozenset[str] = frozenset(PERMISSION_REGISTRY)
VIEW_PERMISSION_SET: frozenset[str] = frozenset(
    permission for permission in PERMISSION_REGISTRY if permission.endswith(".view")
)

ADMIN_ROLE_CEILING: frozenset[str] = frozenset(
    {
        "inquiries.view",
        "inquiries.create",
        "inquiries.edit",
        "inquiries.verify",
        "customers.view",
        "customers.edit",
        "offers.view",
        "offers.prepare",
        "offers.version.create",
        "offers.pdf.generate",
        "offers.send",
        "offers.status.change",
        "offers.timing.acknowledge",
        "orders.view",
        "orders.version.create",
        "orders.print.confirm",
        "orders.effective.set",
        "orders.ready.release",
        "orders.pause",
        "orders.cancel",
        "catalog.view",
        "catalog.edit",
        "prices.view",
        "prices.edit",
        "calendar.view",
        "queue.view",
        "documents.view",
        "users.view",
        "users.create",
        "users.edit",
        "users.deactivate",
        "users.reactivate",
        "users.password.reset",
        "users.permissions.assign",
        "users.roles.assign",
        "settings.view",
    }
)

USER_ROLE_CEILING: frozenset[str] = frozenset(
    {
        "inquiries.view",
        "inquiries.create",
        "inquiries.edit",
        "inquiries.verify",
        "customers.view",
        "customers.edit",
        "offers.view",
        "offers.prepare",
        "offers.version.create",
        "offers.pdf.generate",
        "offers.send",
        "offers.status.change",
        "offers.timing.acknowledge",
        "orders.view",
        "orders.version.create",
        "orders.print.confirm",
        "orders.effective.set",
        "orders.ready.release",
        "orders.pause",
        "orders.cancel",
        "catalog.view",
        "catalog.edit",
        "prices.view",
        "prices.edit",
        "calendar.view",
        "queue.view",
        "documents.view",
    }
)

ROLE_CEILINGS: dict[EmployeeRole, frozenset[str]] = {
    "SUPERADMIN": PERMISSION_SET,
    "ADMIN": ADMIN_ROLE_CEILING,
    "USER": USER_ROLE_CEILING,
    "VIEWER": VIEW_PERMISSION_SET,
}

ROLE_DEFAULT_GRANTS: dict[EmployeeRole, frozenset[str]] = {
    "SUPERADMIN": PERMISSION_SET,
    "ADMIN": frozenset(
        {
            "inquiries.view",
            "inquiries.create",
            "inquiries.edit",
            "inquiries.verify",
            "customers.view",
            "customers.edit",
            "offers.view",
            "offers.prepare",
            "offers.version.create",
            "offers.pdf.generate",
            "offers.send",
            "offers.status.change",
            "offers.timing.acknowledge",
            "orders.view",
            "orders.version.create",
            "orders.print.confirm",
            "orders.effective.set",
            "orders.ready.release",
            "orders.pause",
            "orders.cancel",
            "calendar.view",
            "queue.view",
            "documents.view",
            "users.view",
            "users.create",
            "users.edit",
            "users.deactivate",
            "users.reactivate",
            "users.password.reset",
            "users.permissions.assign",
            "users.roles.assign",
            "settings.view",
        }
    ),
    "USER": frozenset(
        {
            "inquiries.view",
            "inquiries.create",
            "inquiries.edit",
            "customers.view",
            "offers.view",
            "offers.prepare",
            "offers.version.create",
            "documents.view",
            "orders.view",
            "calendar.view",
            "queue.view",
        }
    ),
    "VIEWER": frozenset(),
}

_USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")


def validate_role(value: str) -> EmployeeRole:
    if value not in ROLE_SET:
        raise ValueError(f"role must be one of {sorted(ROLE_SET)}, got {value!r}")
    return cast(EmployeeRole, value)


def validate_permission_code(value: str) -> str:
    if value not in PERMISSION_SET:
        raise ValueError(
            f"permission_code must be one of the AUTH_RBAC_V1 registry, got {value!r}"
        )
    return value


def normalize_username(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("username must be a string")
    normalized = value.strip().lower()
    if not _USERNAME_RE.fullmatch(normalized):
        raise ValueError(
            "username must be 3-64 chars of lowercase letters, digits, dot, dash, underscore"
        )
    return normalized


def normalize_optional_email(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("email must be a string or null")
    normalized = value.strip().lower()
    if not normalized:
        return None
    if "@" not in normalized or len(normalized) > 320:
        raise ValueError("email must be a valid address-like string")
    return normalized


def validate_display_name(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("display_name must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError("display_name must not be empty")
    if len(normalized) > 200:
        raise ValueError("display_name exceeds length limit")
    return normalized


def role_ceiling(role: EmployeeRole) -> frozenset[str]:
    return ROLE_CEILINGS[role]


def role_default_grants(role: EmployeeRole) -> frozenset[str]:
    return ROLE_DEFAULT_GRANTS[role]


def effective_permissions(
    role: EmployeeRole, explicit_permissions: set[str] | frozenset[str]
) -> frozenset[str]:
    ceiling = role_ceiling(role)
    return frozenset(
        permission for permission in explicit_permissions if permission in ceiling
    )


def ensure_permissions_within_role(role: EmployeeRole, permissions: set[str]) -> None:
    for permission in permissions:
        validate_permission_code(permission)
    overflow = permissions.difference(role_ceiling(role))
    if overflow:
        raise ValueError(f"permissions exceed {role} ceiling: {sorted(overflow)}")


def manageable_roles_for(role: EmployeeRole) -> frozenset[EmployeeRole]:
    if role == "SUPERADMIN":
        return frozenset(_ROLE_VALUES)
    if role == "ADMIN":
        return frozenset({"USER", "VIEWER"})
    return frozenset()


@dataclass(frozen=True)
class EmployeeAccount:
    id: str
    username: str
    email: str | None
    display_name: str
    password_hash: str
    role: EmployeeRole
    is_active: bool
    must_change_password: bool
    created_at: datetime
    updated_at: datetime
    deactivated_at: datetime | None
    last_login_at: datetime | None
    auth_version: int


@dataclass(frozen=True)
class EmployeeSession:
    id: str
    account_id: str
    token_hash: str
    csrf_token_hash: str
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    revoked_reason: str | None
    auth_version: int


@dataclass(frozen=True)
class SecurityAuditEvent:
    event_id: str
    occurred_at: datetime
    actor_type: ActorType
    actor_account_id: str | None
    actor_display_name_snapshot: str | None
    actor_role_snapshot: EmployeeRole | None
    session_id: str | None
    action: str
    target_type: str
    target_id: str | None
    permission_code: str | None
    outcome: AuditOutcome
    metadata_json: str


@dataclass(frozen=True)
class AuthenticatedEmployee:
    account: EmployeeAccount
    session: EmployeeSession
    application_access_allowed: bool
    effective_permissions: frozenset[str]


@dataclass(frozen=True)
class SessionLoginResult:
    account: EmployeeAccount
    session: EmployeeSession
    session_token: str
    csrf_token: str
    application_access_allowed: bool
    effective_permissions: frozenset[str]


@dataclass(frozen=True)
class AuthIntrospection:
    kind: Literal["employee_session", "service_token", "public"]
    authenticated: bool
    application_access_allowed: bool = False
    account: EmployeeAccount | None = None
    effective_permissions: frozenset[str] = frozenset()
    service_id: str | None = None


@dataclass(frozen=True)
class EmployeeAccountSummary:
    id: str
    username: str
    email: str | None
    display_name: str
    role: EmployeeRole
    is_active: bool
    must_change_password: bool
    created_at: datetime
    updated_at: datetime
    deactivated_at: datetime | None
    last_login_at: datetime | None
    read_only: bool = False


@dataclass(frozen=True)
class EmployeeAccountDetail:
    id: str
    username: str
    email: str | None
    display_name: str
    role: EmployeeRole
    is_active: bool
    must_change_password: bool
    created_at: datetime
    updated_at: datetime
    deactivated_at: datetime | None
    last_login_at: datetime | None
    read_only: bool
    explicit_permissions: frozenset[str]
    effective_permissions: frozenset[str]


@dataclass(frozen=True)
class SecurityAuditEventView:
    event_id: str
    occurred_at: datetime
    actor_account_id: str | None
    actor_display_name_snapshot: str | None
    actor_role_snapshot: EmployeeRole | None
    action: str
    target_type: str
    target_id: str | None
    permission_code: str | None
    outcome: AuditOutcome
    metadata: dict[str, object]


@dataclass(frozen=True)
class PasswordResetResult:
    account: EmployeeAccount
    temporary_password: str | None = None
