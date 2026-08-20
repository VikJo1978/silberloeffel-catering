import sqlite3

from catering_system.domain.employee_auth import effective_permissions
from catering_system.repositories.sqlite_employee_auth_repository import (
    _migration_1_create_employee_accounts,
    _migration_2_create_account_permissions,
    _migration_6_grant_orders_delete_to_existing_superadmins,
)


def _insert_account(connection: sqlite3.Connection, account_id: str, role: str) -> None:
    connection.execute(
        """
        INSERT INTO employee_accounts (
            account_id, username, email, display_name, password_hash, role,
            is_active, must_change_password, created_at, updated_at,
            deactivated_at, last_login_at, auth_version
        ) VALUES (?, ?, NULL, ?, 'hash', ?, 1, 0, '2026-08-20T00:00:00+00:00',
                  '2026-08-20T00:00:00+00:00', NULL, NULL, 1)
        """,
        (account_id, account_id, account_id, role),
    )


def test_migration_grants_orders_delete_only_to_existing_superadmins() -> None:
    connection = sqlite3.connect(":memory:")
    try:
        _migration_1_create_employee_accounts(connection)
        _migration_2_create_account_permissions(connection)
        _insert_account(connection, "legacy-superadmin", "SUPERADMIN")
        _insert_account(connection, "legacy-admin", "ADMIN")

        _migration_6_grant_orders_delete_to_existing_superadmins(connection)
        _migration_6_grant_orders_delete_to_existing_superadmins(connection)

        rows = connection.execute(
            "SELECT account_id, permission_code FROM account_permissions ORDER BY account_id"
        ).fetchall()
        assert rows == [("legacy-superadmin", "orders.delete")]
    finally:
        connection.close()


def test_superadmin_permission_can_still_be_revoked_after_migration() -> None:
    explicit_permissions = {"orders.view"}

    assert effective_permissions("SUPERADMIN", explicit_permissions) == frozenset(
        {"orders.view"}
    )
