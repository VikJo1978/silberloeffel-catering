from catering_system.domain.employee_auth import (
    PERMISSION_SET,
    effective_permissions,
)


def test_superadmin_effective_permissions_follow_current_registry() -> None:
    legacy_permissions = set(PERMISSION_SET) - {"orders.delete"}

    assert "orders.delete" not in legacy_permissions
    assert effective_permissions("SUPERADMIN", legacy_permissions) == PERMISSION_SET


def test_non_superadmin_does_not_gain_unassigned_permission() -> None:
    explicit_permissions = {"orders.view"}

    assert effective_permissions("USER", explicit_permissions) == frozenset(
        {"orders.view"}
    )
