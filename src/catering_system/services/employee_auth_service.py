"""AUTH_RBAC_V1 authentication, session, and account-management services."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

from catering_system.domain.employee_auth import (
    ActorType,
    AuditOutcome,
    AuthIntrospection,
    AuthenticatedEmployee,
    EmployeeAccount,
    EmployeeRole,
    EmployeeSession,
    SecurityAuditEvent,
    SessionLoginResult,
    effective_permissions,
    ensure_permissions_within_role,
    manageable_roles_for,
    normalize_optional_email,
    normalize_username,
    role_default_grants,
    validate_display_name,
    validate_role,
)
from catering_system.repositories.sqlite_employee_auth_repository import (
    SQLiteEmployeeAuthRepository,
)

_SESSION_TTL = timedelta(hours=12)
_SCRYPT_N = 2**15
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_SALT_BYTES = 16
_SCRYPT_KEY_BYTES = 32
_SCRYPT_MAXMEM = 128 * 1024 * 1024
_SESSION_TOKEN_BYTES = 32
_CSRF_TOKEN_BYTES = 32


class AuthenticationError(Exception):
    pass


class AuthorizationError(Exception):
    pass


class LastActiveSuperadminError(Exception):
    pass


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _hash_password(password: str) -> str:
    if not isinstance(password, str) or len(password) < 8:
        raise ValueError("password must be at least 8 characters")
    salt = secrets.token_bytes(_SCRYPT_SALT_BYTES)
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_SCRYPT_KEY_BYTES,
        maxmem=_SCRYPT_MAXMEM,
    )
    return (
        "scrypt"
        f"${_SCRYPT_N}"
        f"${_SCRYPT_R}"
        f"${_SCRYPT_P}"
        f"${base64.urlsafe_b64encode(salt).decode('ascii')}"
        f"${base64.urlsafe_b64encode(derived).decode('ascii')}"
    )


def verify_password(password: str, encoded_hash: str) -> bool:
    try:
        algorithm, n_raw, r_raw, p_raw, salt_raw, derived_raw = encoded_hash.split("$")
    except ValueError:
        return False
    if algorithm != "scrypt":
        return False
    try:
        salt = base64.urlsafe_b64decode(salt_raw.encode("ascii"))
        expected = base64.urlsafe_b64decode(derived_raw.encode("ascii"))
        derived = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=int(n_raw),
            r=int(r_raw),
            p=int(p_raw),
            dklen=len(expected),
            maxmem=_SCRYPT_MAXMEM,
        )
    except Exception:
        return False
    return hmac.compare_digest(derived, expected)


def _redacted_metadata(metadata: dict[str, Any]) -> str:
    redacted: dict[str, Any] = {}
    for key, value in metadata.items():
        lowered = key.lower()
        if any(token in lowered for token in ("password", "token", "secret", "hash")):
            redacted[key] = "[redacted]"
        else:
            redacted[key] = value
    return json.dumps(redacted, sort_keys=True, ensure_ascii=False)


def _session_cookie_value(token: str) -> str:
    return token


class EmployeeAuthService:
    def __init__(
        self,
        repository: SQLiteEmployeeAuthRepository,
        *,
        now: Callable[[], datetime] = _utc_now,
        session_ttl: timedelta = _SESSION_TTL,
        service_tokens: dict[str, str] | None = None,
    ) -> None:
        self.repository = repository
        self._now = now
        self._session_ttl = session_ttl
        self._service_tokens = {
            service_id: token
            for service_id, token in (service_tokens or {}).items()
            if token
        }

    def bootstrap_superadmin(
        self,
        *,
        username: str,
        display_name: str,
        password: str,
        email: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> EmployeeAccount:
        if self.repository.count_accounts() != 0:
            raise ValueError(
                "bootstrap is allowed only when no employee account exists"
            )
        account = self._create_account_record(
            username=username,
            display_name=display_name,
            password=password,
            email=email,
            role="SUPERADMIN",
            must_change_password=True,
        )
        self.repository.add_account(account)
        self.repository.set_explicit_permissions(
            account.id, set(role_default_grants("SUPERADMIN"))
        )
        self._append_audit(
            actor_type="system",
            actor_account=None,
            session_id=None,
            action="auth.bootstrap_superadmin",
            target_type="employee_account",
            target_id=account.id,
            permission_code=None,
            outcome="success",
            metadata=metadata or {"username": account.username},
        )
        self._append_audit(
            actor_type="system",
            actor_account=None,
            session_id=None,
            action="auth.account_created",
            target_type="employee_account",
            target_id=account.id,
            permission_code=None,
            outcome="success",
            metadata={"role": account.role, "username": account.username},
        )
        return account

    def create_account(
        self,
        actor: AuthenticatedEmployee,
        *,
        username: str,
        display_name: str,
        password: str,
        role: str,
        email: str | None = None,
        explicit_permissions: set[str] | None = None,
        must_change_password: bool = True,
    ) -> EmployeeAccount:
        target_role = validate_role(role)
        self._assert_can_manage_role(actor, target_role)
        self._assert_permission(actor, "users.create")
        account = self._create_account_record(
            username=username,
            display_name=display_name,
            password=password,
            email=email,
            role=target_role,
            must_change_password=must_change_password,
        )
        permissions = (
            set(role_default_grants(target_role))
            if explicit_permissions is None
            else set(explicit_permissions)
        )
        ensure_permissions_within_role(target_role, permissions)
        if actor.account.role == "ADMIN":
            overflow = permissions.difference(actor.effective_permissions)
            if overflow:
                raise AuthorizationError(
                    f"ADMIN may grant only own effective permissions: {sorted(overflow)}"
                )
        self.repository.add_account(account)
        self.repository.set_explicit_permissions(account.id, permissions)
        self._append_audit(
            actor_type="employee",
            actor_account=actor.account,
            session_id=actor.session.id,
            action="auth.account_created",
            target_type="employee_account",
            target_id=account.id,
            permission_code=None,
            outcome="success",
            metadata={"role": account.role, "username": account.username},
        )
        return account

    def set_account_permissions(
        self,
        actor: AuthenticatedEmployee,
        target_account_id: str,
        permissions: set[str],
    ) -> EmployeeAccount:
        self._assert_permission(actor, "users.permissions.assign")
        target = self._require_account(target_account_id)
        self._assert_can_manage_existing_account(actor, target)
        ensure_permissions_within_role(target.role, permissions)
        if actor.account.role == "ADMIN":
            overflow = permissions.difference(actor.effective_permissions)
            if overflow:
                raise AuthorizationError(
                    f"ADMIN may grant only own effective permissions: {sorted(overflow)}"
                )
        self.repository.set_explicit_permissions(target.id, permissions)
        self._append_audit(
            actor_type="employee",
            actor_account=actor.account,
            session_id=actor.session.id,
            action="auth.permission_changed",
            target_type="employee_account",
            target_id=target.id,
            permission_code=None,
            outcome="success",
            metadata={"permissions": sorted(permissions)},
        )
        return target

    def change_account_role(
        self, actor: AuthenticatedEmployee, target_account_id: str, new_role: str
    ) -> EmployeeAccount:
        self._assert_permission(actor, "users.roles.assign")
        target = self._require_account(target_account_id)
        next_role = validate_role(new_role)
        self._assert_can_manage_role(actor, next_role)
        self._assert_can_manage_existing_account(actor, target)
        if target.role == "SUPERADMIN" and next_role != "SUPERADMIN":
            self._assert_not_last_active_superadmin(target)
        updated = replace(
            target,
            role=next_role,
            updated_at=self._now(),
        )
        self.repository.update_account(updated)
        current_permissions = self.repository.get_explicit_permissions(target.id)
        self.repository.set_explicit_permissions(
            target.id, set(effective_permissions(next_role, current_permissions))
        )
        self._append_audit(
            actor_type="employee",
            actor_account=actor.account,
            session_id=actor.session.id,
            action="auth.role_changed",
            target_type="employee_account",
            target_id=target.id,
            permission_code=None,
            outcome="success",
            metadata={"role": next_role},
        )
        return updated

    def deactivate_account(
        self, actor: AuthenticatedEmployee, target_account_id: str
    ) -> EmployeeAccount:
        self._assert_permission(actor, "users.deactivate")
        target = self._require_account(target_account_id)
        self._assert_can_manage_existing_account(actor, target)
        if target.role == "SUPERADMIN":
            self._assert_not_last_active_superadmin(target)
        now = self._now()
        updated = replace(
            target,
            is_active=False,
            updated_at=now,
            deactivated_at=now,
            auth_version=target.auth_version + 1,
        )
        self.repository.update_account(updated)
        self.repository.revoke_sessions_for_account(
            target.id, revoked_at=now, reason="account_deactivated"
        )
        self._append_audit(
            actor_type="employee",
            actor_account=actor.account,
            session_id=actor.session.id,
            action="auth.account_deactivated",
            target_type="employee_account",
            target_id=target.id,
            permission_code=None,
            outcome="success",
            metadata={"username": target.username},
        )
        return updated

    def reactivate_account(
        self, actor: AuthenticatedEmployee, target_account_id: str
    ) -> EmployeeAccount:
        self._assert_permission(actor, "users.reactivate")
        target = self._require_account(target_account_id)
        self._assert_can_manage_existing_account(actor, target)
        updated = replace(
            target,
            is_active=True,
            updated_at=self._now(),
            deactivated_at=None,
        )
        self.repository.update_account(updated)
        self._append_audit(
            actor_type="employee",
            actor_account=actor.account,
            session_id=actor.session.id,
            action="auth.account_reactivated",
            target_type="employee_account",
            target_id=target.id,
            permission_code=None,
            outcome="success",
            metadata={"username": target.username},
        )
        return updated

    def authenticate(self, *, username: str, password: str) -> SessionLoginResult:
        normalized_username = normalize_username(username)
        account = self.repository.get_account_by_username(normalized_username)
        if account is None or not verify_password(password, account.password_hash):
            self._append_audit(
                actor_type="public",
                actor_account=None,
                session_id=None,
                action="auth.login",
                target_type="employee_account",
                target_id=account.id if account is not None else None,
                permission_code=None,
                outcome="failure",
                metadata={"username": normalized_username},
            )
            raise AuthenticationError("invalid credentials")
        if not account.is_active:
            self._append_audit(
                actor_type="public",
                actor_account=None,
                session_id=None,
                action="auth.login",
                target_type="employee_account",
                target_id=account.id,
                permission_code=None,
                outcome="failure",
                metadata={"username": normalized_username, "reason": "inactive"},
            )
            raise AuthenticationError("account is inactive")
        now = self._now()
        updated = replace(account, last_login_at=now, updated_at=now)
        self.repository.update_account(updated)
        session_token = secrets.token_urlsafe(_SESSION_TOKEN_BYTES)
        csrf_token = secrets.token_urlsafe(_CSRF_TOKEN_BYTES)
        session = EmployeeSession(
            id=str(uuid.uuid4()),
            account_id=updated.id,
            token_hash=_token_hash(session_token),
            csrf_token_hash=_token_hash(csrf_token),
            created_at=now,
            last_seen_at=now,
            expires_at=now + self._session_ttl,
            revoked_at=None,
            revoked_reason=None,
            auth_version=updated.auth_version,
        )
        self.repository.create_session(session)
        resolved_permissions = self.repository.get_explicit_permissions(updated.id)
        self._append_audit(
            actor_type="employee",
            actor_account=updated,
            session_id=session.id,
            action="auth.login",
            target_type="employee_account",
            target_id=updated.id,
            permission_code=None,
            outcome="success",
            metadata={"username": updated.username},
        )
        return SessionLoginResult(
            account=updated,
            session=session,
            session_token=session_token,
            csrf_token=csrf_token,
            effective_permissions=effective_permissions(
                updated.role, resolved_permissions
            ),
        )

    def authenticate_session(self, session_token: str) -> AuthenticatedEmployee:
        session = self.repository.get_session_by_token_hash(_token_hash(session_token))
        if session is None:
            raise AuthenticationError("session not found")
        now = self._now()
        if session.revoked_at is not None:
            raise AuthenticationError("session revoked")
        if session.expires_at <= now:
            revoked = replace(
                session,
                revoked_at=now,
                revoked_reason="expired",
            )
            self.repository.update_session(revoked)
            raise AuthenticationError("session expired")
        account = self._require_account(session.account_id)
        if not account.is_active:
            raise AuthenticationError("account is inactive")
        if session.auth_version != account.auth_version:
            revoked = replace(
                session,
                revoked_at=now,
                revoked_reason="auth_version_changed",
            )
            self.repository.update_session(revoked)
            raise AuthenticationError("session invalidated")
        touched = replace(session, last_seen_at=now)
        self.repository.update_session(touched)
        resolved_permissions = self.repository.get_explicit_permissions(account.id)
        return AuthenticatedEmployee(
            account=account,
            session=touched,
            effective_permissions=effective_permissions(
                account.role, resolved_permissions
            ),
        )

    def validate_csrf(self, session: EmployeeSession, csrf_token: str) -> None:
        if not csrf_token or not hmac.compare_digest(
            session.csrf_token_hash, _token_hash(csrf_token)
        ):
            raise AuthenticationError("invalid csrf token")

    def logout(self, employee: AuthenticatedEmployee) -> None:
        revoked = replace(
            employee.session,
            revoked_at=self._now(),
            revoked_reason="logout",
        )
        self.repository.update_session(revoked)
        self._append_audit(
            actor_type="employee",
            actor_account=employee.account,
            session_id=employee.session.id,
            action="auth.logout",
            target_type="employee_account",
            target_id=employee.account.id,
            permission_code=None,
            outcome="success",
            metadata={"username": employee.account.username},
        )

    def change_password(
        self,
        employee: AuthenticatedEmployee,
        *,
        current_password: str,
        new_password: str,
    ) -> EmployeeAccount:
        if not verify_password(current_password, employee.account.password_hash):
            raise AuthenticationError("current password is invalid")
        now = self._now()
        updated = replace(
            employee.account,
            password_hash=_hash_password(new_password),
            must_change_password=False,
            updated_at=now,
            auth_version=employee.account.auth_version + 1,
        )
        self.repository.update_account(updated)
        self.repository.revoke_sessions_for_account(
            employee.account.id, revoked_at=now, reason="password_changed"
        )
        self._append_audit(
            actor_type="employee",
            actor_account=employee.account,
            session_id=employee.session.id,
            action="auth.password_changed",
            target_type="employee_account",
            target_id=employee.account.id,
            permission_code=None,
            outcome="success",
            metadata={"username": employee.account.username},
        )
        return updated

    def reset_password(
        self,
        *,
        actor: AuthenticatedEmployee | None,
        target_username: str,
        temporary_password: str,
        recovery: bool = False,
    ) -> EmployeeAccount:
        target = self._require_account_by_username(target_username)
        actor_type: ActorType
        if actor is not None:
            self._assert_permission(actor, "users.password.reset")
            self._assert_can_manage_existing_account(actor, target)
            actor_type = "employee"
            actor_account = actor.account
            session_id = actor.session.id
        else:
            actor_type = "system"
            actor_account = None
            session_id = None
        now = self._now()
        updated = replace(
            target,
            password_hash=_hash_password(temporary_password),
            must_change_password=True,
            updated_at=now,
            auth_version=target.auth_version + 1,
        )
        self.repository.update_account(updated)
        self.repository.revoke_sessions_for_account(
            target.id, revoked_at=now, reason="password_reset"
        )
        self._append_audit(
            actor_type=actor_type,
            actor_account=actor_account,
            session_id=session_id,
            action="auth.password_reset",
            target_type="employee_account",
            target_id=target.id,
            permission_code=None,
            outcome="success",
            metadata={"username": target.username, "recovery": recovery},
        )
        return updated

    def introspect(
        self,
        *,
        session_token: str | None,
        bearer_token: str | None,
    ) -> AuthIntrospection:
        if session_token:
            try:
                employee = self.authenticate_session(session_token)
            except AuthenticationError:
                pass
            else:
                return AuthIntrospection(
                    kind="employee_session",
                    authenticated=True,
                    account=employee.account,
                    effective_permissions=employee.effective_permissions,
                )
        if bearer_token:
            for service_id, token in self._service_tokens.items():
                if hmac.compare_digest(token, bearer_token):
                    return AuthIntrospection(
                        kind="service_token",
                        authenticated=True,
                        service_id=service_id,
                    )
        return AuthIntrospection(kind="public", authenticated=False)

    def _create_account_record(
        self,
        *,
        username: str,
        display_name: str,
        password: str,
        role: EmployeeRole,
        email: str | None,
        must_change_password: bool,
    ) -> EmployeeAccount:
        now = self._now()
        return EmployeeAccount(
            id=str(uuid.uuid4()),
            username=normalize_username(username),
            email=normalize_optional_email(email),
            display_name=validate_display_name(display_name),
            password_hash=_hash_password(password),
            role=role,
            is_active=True,
            must_change_password=must_change_password,
            created_at=now,
            updated_at=now,
            deactivated_at=None,
            last_login_at=None,
            auth_version=1,
        )

    def _require_account(self, account_id: str) -> EmployeeAccount:
        account = self.repository.get_account_by_id(account_id)
        if account is None:
            raise ValueError(f"unknown account_id {account_id!r}")
        return account

    def _require_account_by_username(self, username: str) -> EmployeeAccount:
        account = self.repository.get_account_by_username(normalize_username(username))
        if account is None:
            raise ValueError(f"unknown username {username!r}")
        return account

    def _assert_can_manage_role(
        self, actor: AuthenticatedEmployee, target_role: EmployeeRole
    ) -> None:
        if target_role not in manageable_roles_for(actor.account.role):
            raise AuthorizationError(
                f"{actor.account.role} may not manage role {target_role}"
            )

    def _assert_can_manage_existing_account(
        self, actor: AuthenticatedEmployee, target: EmployeeAccount
    ) -> None:
        self._assert_can_manage_role(actor, target.role)
        if actor.account.role == "ADMIN" and target.role == "SUPERADMIN":
            raise AuthorizationError("ADMIN may not manage SUPERADMIN accounts")

    def _assert_permission(
        self, actor: AuthenticatedEmployee, permission_code: str
    ) -> None:
        if permission_code not in actor.effective_permissions:
            raise AuthorizationError(f"missing permission {permission_code}")

    def _assert_not_last_active_superadmin(self, target: EmployeeAccount) -> None:
        if target.role != "SUPERADMIN" or not target.is_active:
            return
        if self.repository.count_active_superadmins() <= 1:
            raise LastActiveSuperadminError(
                "cannot remove or deactivate the last active SUPERADMIN"
            )

    def _append_audit(
        self,
        *,
        actor_type: ActorType,
        actor_account: EmployeeAccount | None,
        session_id: str | None,
        action: str,
        target_type: str,
        target_id: str | None,
        permission_code: str | None,
        outcome: AuditOutcome,
        metadata: dict[str, Any],
    ) -> None:
        self.repository.append_audit_event(
            SecurityAuditEvent(
                event_id=str(uuid.uuid4()),
                occurred_at=self._now(),
                actor_type=actor_type,
                actor_account_id=actor_account.id
                if actor_account is not None
                else None,
                actor_display_name_snapshot=(
                    actor_account.display_name if actor_account is not None else None
                ),
                actor_role_snapshot=actor_account.role
                if actor_account is not None
                else None,
                session_id=session_id,
                action=action,
                target_type=target_type,
                target_id=target_id,
                permission_code=permission_code,
                outcome=outcome,
                metadata_json=_redacted_metadata(metadata),
            )
        )
