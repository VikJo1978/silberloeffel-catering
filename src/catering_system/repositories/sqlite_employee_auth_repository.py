"""SQLite persistence for AUTH_RBAC_V1 employee auth foundation."""

from __future__ import annotations

import json
import sqlite3
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path

from catering_system.domain.employee_auth import (
    EmployeeAccount,
    EmployeeSession,
    SecurityAuditEvent,
    validate_permission_code,
    validate_role,
)
from catering_system.repositories.sqlite_migrations import apply_migrations

_CREATE_EMPLOYEE_ACCOUNTS = """
CREATE TABLE IF NOT EXISTS employee_accounts (
    account_id TEXT PRIMARY KEY,
    username TEXT NOT NULL COLLATE NOCASE,
    email TEXT COLLATE NOCASE,
    display_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL,
    is_active INTEGER NOT NULL,
    must_change_password INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deactivated_at TEXT,
    last_login_at TEXT,
    auth_version INTEGER NOT NULL
);
"""

_ACCOUNT_INDEXES = (
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_employee_accounts_username
    ON employee_accounts (username);
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_employee_accounts_email
    ON employee_accounts (email)
    WHERE email IS NOT NULL AND email <> '';
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_employee_accounts_role
    ON employee_accounts (role);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_employee_accounts_active
    ON employee_accounts (is_active, role);
    """,
)

_CREATE_ACCOUNT_PERMISSIONS = """
CREATE TABLE IF NOT EXISTS account_permissions (
    account_id TEXT NOT NULL,
    permission_code TEXT NOT NULL,
    PRIMARY KEY (account_id, permission_code),
    FOREIGN KEY (account_id) REFERENCES employee_accounts (account_id)
);
"""

_ACCOUNT_PERMISSION_INDEX = """
CREATE INDEX IF NOT EXISTS idx_account_permissions_account
ON account_permissions (account_id);
"""

_CREATE_EMPLOYEE_SESSIONS = """
CREATE TABLE IF NOT EXISTS employee_sessions (
    session_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    token_hash TEXT NOT NULL,
    csrf_token_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked_at TEXT,
    revoked_reason TEXT,
    auth_version INTEGER NOT NULL,
    FOREIGN KEY (account_id) REFERENCES employee_accounts (account_id)
);
"""

_SESSION_INDEXES = (
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_employee_sessions_token_hash
    ON employee_sessions (token_hash);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_employee_sessions_account
    ON employee_sessions (account_id);
    """,
)

_CREATE_SECURITY_AUDIT_EVENTS = """
CREATE TABLE IF NOT EXISTS security_audit_events (
    event_id TEXT PRIMARY KEY,
    occurred_at TEXT NOT NULL,
    actor_type TEXT NOT NULL,
    actor_account_id TEXT,
    actor_display_name_snapshot TEXT,
    actor_role_snapshot TEXT,
    session_id TEXT,
    action TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT,
    permission_code TEXT,
    outcome TEXT NOT NULL,
    metadata_json TEXT NOT NULL
);
"""

_AUDIT_INDEXES = (
    """
    CREATE INDEX IF NOT EXISTS idx_security_audit_events_occurred_at
    ON security_audit_events (occurred_at);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_security_audit_events_actor
    ON security_audit_events (actor_account_id, occurred_at);
    """,
)

_AUDIT_APPEND_ONLY_TRIGGERS = (
    """
    CREATE TRIGGER IF NOT EXISTS trg_security_audit_events_no_update
    BEFORE UPDATE ON security_audit_events
    BEGIN
        SELECT RAISE(ABORT, 'security audit events are append-only');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_security_audit_events_no_delete
    BEFORE DELETE ON security_audit_events
    BEGIN
        SELECT RAISE(ABORT, 'security audit events are append-only');
    END
    """,
)


def _migration_1_create_employee_accounts(connection: sqlite3.Connection) -> None:
    connection.execute(_CREATE_EMPLOYEE_ACCOUNTS)
    for statement in _ACCOUNT_INDEXES:
        connection.execute(statement)


def _migration_2_create_account_permissions(connection: sqlite3.Connection) -> None:
    connection.execute(_CREATE_ACCOUNT_PERMISSIONS)
    connection.execute(_ACCOUNT_PERMISSION_INDEX)


def _migration_3_create_employee_sessions(connection: sqlite3.Connection) -> None:
    connection.execute(_CREATE_EMPLOYEE_SESSIONS)
    for statement in _SESSION_INDEXES:
        connection.execute(statement)


def _migration_4_create_security_audit_events(connection: sqlite3.Connection) -> None:
    connection.execute(_CREATE_SECURITY_AUDIT_EVENTS)
    for statement in _AUDIT_INDEXES:
        connection.execute(statement)
    for statement in _AUDIT_APPEND_ONLY_TRIGGERS:
        connection.execute(statement)


_MIGRATIONS = (
    (1, "create_employee_accounts", _migration_1_create_employee_accounts),
    (2, "create_account_permissions", _migration_2_create_account_permissions),
    (3, "create_employee_sessions", _migration_3_create_employee_sessions),
    (4, "create_security_audit_events", _migration_4_create_security_audit_events),
)


class SQLiteEmployeeAuthRepository:
    def __init__(self, db_path: str | Path) -> None:
        self._conn = sqlite3.connect(str(db_path))
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._manage_transactions = True
        try:
            apply_migrations(self._conn, "employee_auth", _MIGRATIONS)
        except Exception:
            self._conn.close()
            raise

    @classmethod
    def from_connection(
        cls, connection: sqlite3.Connection
    ) -> SQLiteEmployeeAuthRepository:
        repo = cls.__new__(cls)
        repo._conn = connection
        repo._conn.execute("PRAGMA foreign_keys = ON")
        repo._manage_transactions = False
        apply_migrations(connection, "employee_auth", _MIGRATIONS)
        return repo

    def _write_scope(self):  # noqa: ANN202
        return self._conn if self._manage_transactions else nullcontext()

    def close(self) -> None:
        self._conn.close()

    def count_accounts(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM employee_accounts").fetchone()
        assert row is not None
        return int(row[0])

    def count_active_superadmins(self) -> int:
        row = self._conn.execute(
            """
            SELECT COUNT(*) FROM employee_accounts
            WHERE role = 'SUPERADMIN' AND is_active = 1
            """
        ).fetchone()
        assert row is not None
        return int(row[0])

    def add_account(self, account: EmployeeAccount) -> None:
        with self._write_scope():
            self._conn.execute(
                """
                INSERT INTO employee_accounts (
                    account_id, username, email, display_name, password_hash, role,
                    is_active, must_change_password, created_at, updated_at,
                    deactivated_at, last_login_at, auth_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    account.id,
                    account.username,
                    account.email,
                    account.display_name,
                    account.password_hash,
                    account.role,
                    int(account.is_active),
                    int(account.must_change_password),
                    account.created_at.isoformat(),
                    account.updated_at.isoformat(),
                    account.deactivated_at.isoformat()
                    if account.deactivated_at is not None
                    else None,
                    account.last_login_at.isoformat()
                    if account.last_login_at is not None
                    else None,
                    account.auth_version,
                ),
            )

    def update_account(self, account: EmployeeAccount) -> None:
        with self._write_scope():
            updated = self._conn.execute(
                """
                UPDATE employee_accounts
                SET username = ?, email = ?, display_name = ?, password_hash = ?,
                    role = ?, is_active = ?, must_change_password = ?,
                    updated_at = ?, deactivated_at = ?, last_login_at = ?,
                    auth_version = ?
                WHERE account_id = ?
                """,
                (
                    account.username,
                    account.email,
                    account.display_name,
                    account.password_hash,
                    account.role,
                    int(account.is_active),
                    int(account.must_change_password),
                    account.updated_at.isoformat(),
                    account.deactivated_at.isoformat()
                    if account.deactivated_at is not None
                    else None,
                    account.last_login_at.isoformat()
                    if account.last_login_at is not None
                    else None,
                    account.auth_version,
                    account.id,
                ),
            ).rowcount
            if updated != 1:
                raise KeyError(account.id)

    def get_account_by_id(self, account_id: str) -> EmployeeAccount | None:
        row = self._conn.execute(
            "SELECT * FROM employee_accounts WHERE account_id = ?", (account_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_account(row)

    def get_account_by_username(self, username: str) -> EmployeeAccount | None:
        row = self._conn.execute(
            "SELECT * FROM employee_accounts WHERE username = ?", (username,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_account(row)

    def set_explicit_permissions(self, account_id: str, permissions: set[str]) -> None:
        for permission in permissions:
            validate_permission_code(permission)
        with self._write_scope():
            self._conn.execute(
                "DELETE FROM account_permissions WHERE account_id = ?", (account_id,)
            )
            self._conn.executemany(
                """
                INSERT INTO account_permissions (account_id, permission_code)
                VALUES (?, ?)
                """,
                [(account_id, permission) for permission in sorted(permissions)],
            )

    def get_explicit_permissions(self, account_id: str) -> set[str]:
        rows = self._conn.execute(
            """
            SELECT permission_code FROM account_permissions
            WHERE account_id = ?
            ORDER BY permission_code
            """,
            (account_id,),
        ).fetchall()
        return {validate_permission_code(row[0]) for row in rows}

    def create_session(self, session: EmployeeSession) -> None:
        with self._write_scope():
            self._conn.execute(
                """
                INSERT INTO employee_sessions (
                    session_id, account_id, token_hash, csrf_token_hash,
                    created_at, last_seen_at, expires_at, revoked_at,
                    revoked_reason, auth_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session.id,
                    session.account_id,
                    session.token_hash,
                    session.csrf_token_hash,
                    session.created_at.isoformat(),
                    session.last_seen_at.isoformat(),
                    session.expires_at.isoformat(),
                    session.revoked_at.isoformat()
                    if session.revoked_at is not None
                    else None,
                    session.revoked_reason,
                    session.auth_version,
                ),
            )

    def get_session_by_token_hash(self, token_hash: str) -> EmployeeSession | None:
        row = self._conn.execute(
            "SELECT * FROM employee_sessions WHERE token_hash = ?",
            (token_hash,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_session(row)

    def update_session(self, session: EmployeeSession) -> None:
        with self._write_scope():
            updated = self._conn.execute(
                """
                UPDATE employee_sessions
                SET last_seen_at = ?, expires_at = ?, revoked_at = ?, revoked_reason = ?,
                    auth_version = ?
                WHERE session_id = ?
                """,
                (
                    session.last_seen_at.isoformat(),
                    session.expires_at.isoformat(),
                    session.revoked_at.isoformat()
                    if session.revoked_at is not None
                    else None,
                    session.revoked_reason,
                    session.auth_version,
                    session.id,
                ),
            ).rowcount
            if updated != 1:
                raise KeyError(session.id)

    def revoke_sessions_for_account(
        self, account_id: str, *, revoked_at: datetime, reason: str
    ) -> int:
        with self._write_scope():
            return self._conn.execute(
                """
                UPDATE employee_sessions
                SET revoked_at = ?, revoked_reason = ?
                WHERE account_id = ? AND revoked_at IS NULL
                """,
                (revoked_at.isoformat(), reason, account_id),
            ).rowcount

    def append_audit_event(self, event: SecurityAuditEvent) -> None:
        json.loads(event.metadata_json)
        with self._write_scope():
            self._conn.execute(
                """
                INSERT INTO security_audit_events (
                    event_id, occurred_at, actor_type, actor_account_id,
                    actor_display_name_snapshot, actor_role_snapshot, session_id,
                    action, target_type, target_id, permission_code, outcome,
                    metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.occurred_at.isoformat(),
                    event.actor_type,
                    event.actor_account_id,
                    event.actor_display_name_snapshot,
                    event.actor_role_snapshot,
                    event.session_id,
                    event.action,
                    event.target_type,
                    event.target_id,
                    event.permission_code,
                    event.outcome,
                    event.metadata_json,
                ),
            )

    def list_audit_events(self) -> list[SecurityAuditEvent]:
        rows = self._conn.execute(
            "SELECT * FROM security_audit_events ORDER BY occurred_at, event_id"
        ).fetchall()
        return [self._row_to_audit_event(row) for row in rows]

    @staticmethod
    def _row_to_account(row: tuple) -> EmployeeAccount:
        return EmployeeAccount(
            id=row[0],
            username=row[1],
            email=row[2],
            display_name=row[3],
            password_hash=row[4],
            role=validate_role(row[5]),
            is_active=bool(row[6]),
            must_change_password=bool(row[7]),
            created_at=datetime.fromisoformat(row[8]),
            updated_at=datetime.fromisoformat(row[9]),
            deactivated_at=datetime.fromisoformat(row[10]) if row[10] else None,
            last_login_at=datetime.fromisoformat(row[11]) if row[11] else None,
            auth_version=int(row[12]),
        )

    @staticmethod
    def _row_to_session(row: tuple) -> EmployeeSession:
        return EmployeeSession(
            id=row[0],
            account_id=row[1],
            token_hash=row[2],
            csrf_token_hash=row[3],
            created_at=datetime.fromisoformat(row[4]),
            last_seen_at=datetime.fromisoformat(row[5]),
            expires_at=datetime.fromisoformat(row[6]),
            revoked_at=datetime.fromisoformat(row[7]) if row[7] else None,
            revoked_reason=row[8],
            auth_version=int(row[9]),
        )

    @staticmethod
    def _row_to_audit_event(row: tuple) -> SecurityAuditEvent:
        role = validate_role(row[5]) if row[5] is not None else None
        return SecurityAuditEvent(
            event_id=row[0],
            occurred_at=datetime.fromisoformat(row[1]),
            actor_type=row[2],
            actor_account_id=row[3],
            actor_display_name_snapshot=row[4],
            actor_role_snapshot=role,
            session_id=row[6],
            action=row[7],
            target_type=row[8],
            target_id=row[9],
            permission_code=row[10],
            outcome=row[11],
            metadata_json=row[12],
        )
