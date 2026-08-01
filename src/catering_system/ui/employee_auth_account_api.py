"""Account-management HTTP routes for AUTH_RBAC_V1 (AUTH-2B)."""

from __future__ import annotations

from typing import Callable
from urllib.parse import parse_qs

from catering_system.domain.employee_auth import (
    EmployeeAccountDetail,
    EmployeeAccountSummary,
    SecurityAuditEventView,
)
from catering_system.services.employee_auth_service import (
    AccountConflictError,
    AccountNotFoundError,
    AuthenticationError,
    AuthorizationError,
    CsrfValidationError,
    EmployeeAuthService,
    LastActiveSuperadminError,
)

_ACCOUNT_AUDIT_LIST_DEFAULT_LIMIT = 100
_ACCOUNT_AUDIT_LIST_MAX_LIMIT = 500


def _reject_unknown_keys(body: dict[str, object], allowed: set[str]) -> None:
    unknown = set(body).difference(allowed)
    if unknown:
        raise ValueError(f"unknown fields: {sorted(unknown)}")


def parse_accounts_route(path: str) -> tuple[str, str | None, str | None]:
    if path == "/auth/accounts":
        return ("collection", None, None)
    prefix = "/auth/accounts/"
    if not path.startswith(prefix):
        return ("", None, None)
    remainder = path[len(prefix) :]
    if not remainder:
        return ("", None, None)
    parts = remainder.split("/")
    account_id = parts[0]
    action = parts[1] if len(parts) > 1 else None
    if len(parts) > 2:
        raise ValueError("invalid account route")
    return ("member", account_id, action)


def account_summary_json(summary: EmployeeAccountSummary) -> dict[str, object]:
    return {
        "id": summary.id,
        "username": summary.username,
        "email": summary.email,
        "display_name": summary.display_name,
        "role": summary.role,
        "is_active": summary.is_active,
        "must_change_password": summary.must_change_password,
        "created_at": summary.created_at.isoformat(),
        "updated_at": summary.updated_at.isoformat(),
        "deactivated_at": (
            summary.deactivated_at.isoformat() if summary.deactivated_at else None
        ),
        "last_login_at": (
            summary.last_login_at.isoformat() if summary.last_login_at else None
        ),
        "read_only": summary.read_only,
    }


def account_detail_json(detail: EmployeeAccountDetail) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": detail.id,
        "username": detail.username,
        "email": detail.email,
        "display_name": detail.display_name,
        "role": detail.role,
        "is_active": detail.is_active,
        "must_change_password": detail.must_change_password,
        "created_at": detail.created_at.isoformat(),
        "updated_at": detail.updated_at.isoformat(),
        "deactivated_at": (
            detail.deactivated_at.isoformat() if detail.deactivated_at else None
        ),
        "last_login_at": (
            detail.last_login_at.isoformat() if detail.last_login_at else None
        ),
        "read_only": detail.read_only,
    }
    payload["explicit_permissions"] = sorted(detail.explicit_permissions)
    payload["effective_permissions"] = sorted(detail.effective_permissions)
    return payload


def audit_event_json(event: SecurityAuditEventView) -> dict[str, object]:
    return {
        "event_id": event.event_id,
        "occurred_at": event.occurred_at.isoformat(),
        "actor_account_id": event.actor_account_id,
        "actor_display_name_snapshot": event.actor_display_name_snapshot,
        "actor_role_snapshot": event.actor_role_snapshot,
        "action": event.action,
        "target_type": event.target_type,
        "target_id": event.target_id,
        "permission_code": event.permission_code,
        "outcome": event.outcome,
        "metadata": event.metadata,
    }


def _parse_audit_events_limit(query: str) -> int | None:
    if not query:
        return None
    params = parse_qs(query, keep_blank_values=True)
    if "limit" not in params:
        return None
    raw_values = params["limit"]
    if len(raw_values) != 1 or not raw_values[0].strip():
        raise ValueError(f"limit must be between 1 and {_ACCOUNT_AUDIT_LIST_MAX_LIMIT}")
    try:
        limit = int(raw_values[0])
    except ValueError as exc:
        raise ValueError(
            f"limit must be between 1 and {_ACCOUNT_AUDIT_LIST_MAX_LIMIT}"
        ) from exc
    if limit < 1 or limit > _ACCOUNT_AUDIT_LIST_MAX_LIMIT:
        raise ValueError(f"limit must be between 1 and {_ACCOUNT_AUDIT_LIST_MAX_LIMIT}")
    return limit


def handle_accounts_get(
    service: EmployeeAuthService,
    *,
    route_kind: str,
    account_id: str | None,
    action: str | None,
    employee,
    query: str = "",
) -> tuple[int, dict[str, object]]:
    if route_kind == "collection":
        accounts = service.list_accounts(employee)
        return 200, {"accounts": [account_summary_json(item) for item in accounts]}
    if route_kind != "member" or account_id is None:
        return 404, {"error": "not_found"}
    if action == "audit-events":
        limit = _parse_audit_events_limit(query)
        events = service.list_account_audit_events(employee, account_id, limit=limit)
        return 200, {"events": [audit_event_json(item) for item in events]}
    if action is not None:
        return 404, {"error": "not_found"}
    detail = service.get_account(employee, account_id)
    return 200, {"account": account_detail_json(detail)}


def handle_accounts_post(
    service: EmployeeAuthService,
    *,
    route_kind: str,
    account_id: str | None,
    action: str | None,
    employee,
    body: dict[str, object],
) -> tuple[int, dict[str, object]]:
    if route_kind == "collection":
        _reject_unknown_keys(
            body,
            {
                "username",
                "display_name",
                "email",
                "role",
                "temporary_password",
                "permissions",
                "is_active",
            },
        )
        if body.get("is_active") is False:
            raise ValueError("is_active must be true for new accounts")
        permissions_raw = body.get("permissions")
        permissions = None
        if permissions_raw is not None:
            if not isinstance(permissions_raw, list):
                raise ValueError("permissions must be a list")
            permissions = {str(item) for item in permissions_raw}
        email_value: str | None
        if "email" in body:
            email_value = str(body["email"]) if body["email"] is not None else None
        else:
            email_value = None
        account = service.create_account(
            employee,
            username=str(body.get("username", "")),
            display_name=str(body.get("display_name", "")),
            password=str(body.get("temporary_password", "")),
            role=str(body.get("role", "")),
            email=email_value,
            explicit_permissions=permissions,
            must_change_password=True,
        )
        detail = service.get_account(employee, account.id)
        return 201, {"account": account_detail_json(detail)}

    if route_kind != "member" or account_id is None or action is None:
        return 404, {"error": "not_found"}

    if action == "role":
        _reject_unknown_keys(body, {"role"})
        updated = service.change_account_role(
            employee, account_id, str(body.get("role", ""))
        )
        detail = service.get_account(employee, updated.id)
        return 200, {"account": account_detail_json(detail)}

    if action == "deactivate":
        _reject_unknown_keys(body, set())
        updated = service.deactivate_account(employee, account_id)
        detail = service.get_account(employee, updated.id)
        return 200, {"account": account_detail_json(detail)}

    if action == "reactivate":
        _reject_unknown_keys(body, set())
        updated = service.reactivate_account(employee, account_id)
        detail = service.get_account(employee, updated.id)
        return 200, {"account": account_detail_json(detail)}

    if action == "reset-password":
        _reject_unknown_keys(body, {"temporary_password"})
        temporary_password = body.get("temporary_password")
        if temporary_password is not None and not isinstance(temporary_password, str):
            raise ValueError("temporary_password must be a string")
        result = service.reset_account_password(
            employee,
            account_id,
            temporary_password=(
                str(temporary_password) if temporary_password is not None else None
            ),
        )
        detail = service.get_account(employee, result.account.id)
        payload: dict[str, object] = {"account": account_detail_json(detail)}
        if result.temporary_password is not None:
            payload["temporary_password"] = result.temporary_password
        return 200, payload

    return 404, {"error": "not_found"}


def handle_accounts_patch(
    service: EmployeeAuthService,
    *,
    account_id: str | None,
    action: str | None,
    employee,
    body: dict[str, object],
) -> tuple[int, dict[str, object]]:
    if account_id is None or action is not None:
        return 404, {"error": "not_found"}
    _reject_unknown_keys(body, {"username", "display_name", "email"})
    username = str(body["username"]) if "username" in body else None
    display_name = str(body["display_name"]) if "display_name" in body else None
    if "email" in body:
        detail = service.update_account_profile(
            employee,
            account_id,
            username=username,
            display_name=display_name,
            email=body["email"],
        )
    else:
        detail = service.update_account_profile(
            employee,
            account_id,
            username=username,
            display_name=display_name,
        )
    return 200, {"account": account_detail_json(detail)}


def handle_accounts_put(
    service: EmployeeAuthService,
    *,
    account_id: str | None,
    action: str | None,
    employee,
    body: dict[str, object],
) -> tuple[int, dict[str, object]]:
    if account_id is None or action != "permissions":
        return 404, {"error": "not_found"}
    _reject_unknown_keys(body, {"permissions"})
    permissions_raw = body.get("permissions")
    if not isinstance(permissions_raw, list):
        raise ValueError("permissions must be a list")
    permissions = {str(item) for item in permissions_raw}
    service.set_account_permissions(employee, account_id, permissions)
    detail = service.get_account(employee, account_id)
    return 200, {"account": account_detail_json(detail)}


def map_account_management_error(exc: Exception) -> tuple[int, str]:
    if isinstance(exc, CsrfValidationError):
        return 403, "forbidden"
    if isinstance(exc, AuthenticationError):
        return 401, "unauthorized"
    if isinstance(exc, AuthorizationError):
        return 403, "forbidden"
    if isinstance(exc, AccountNotFoundError):
        return 404, "not_found"
    if isinstance(exc, AccountConflictError):
        return 409, "conflict"
    if isinstance(exc, LastActiveSuperadminError):
        return 409, "last_active_superadmin"
    if isinstance(exc, ValueError):
        return 400, "invalid_request"
    return 500, "internal_error"


def dispatch_account_route(
    service: EmployeeAuthService,
    *,
    method: str,
    path: str,
    employee,
    body: dict[str, object] | None,
    respond: Callable[[int, dict[str, object]], None],
    query: str = "",
) -> bool:
    route_kind, account_id, action = parse_accounts_route(path)
    if route_kind == "":
        return False
    try:
        if method == "GET":
            status, payload = handle_accounts_get(
                service,
                route_kind=route_kind,
                account_id=account_id,
                action=action,
                employee=employee,
                query=query,
            )
        elif method == "POST":
            assert body is not None
            status, payload = handle_accounts_post(
                service,
                route_kind=route_kind,
                account_id=account_id,
                action=action,
                employee=employee,
                body=body,
            )
        elif method == "PATCH":
            assert body is not None
            status, payload = handle_accounts_patch(
                service,
                account_id=account_id,
                action=action,
                employee=employee,
                body=body,
            )
        elif method == "PUT":
            assert body is not None
            status, payload = handle_accounts_put(
                service,
                account_id=account_id,
                action=action,
                employee=employee,
                body=body,
            )
        else:
            return False
    except Exception as exc:  # noqa: BLE001
        status, code = map_account_management_error(exc)
        payload = {"error": code}
        if status == 400 and isinstance(exc, ValueError):
            payload["message"] = str(exc)
        respond(status, payload)
        return True
    respond(status, payload)
    return True
