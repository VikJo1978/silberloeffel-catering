"""Focused regression coverage for maintenance-only Order hard deletion."""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime

import pytest

from catering_system.domain.order import Order, OrderVersion
from catering_system.domain.order_operational_context import (
    OrderVersionOperationalContextSnapshot,
)
from catering_system.repositories.in_memory_order_repository import (
    InMemoryOrderRepository,
)
from catering_system.repositories.order_purge import purge_order_with_dependencies
from catering_system.repositories.sqlite_order_repository import SQLiteOrderRepository
from catering_system.ui.office_panel_order_detail import (
    OrderDetailFormFields,
    _secondary_actions,
)
from catering_system.ui.office_panel_views import OfficePageContext

_NOW = datetime(2026, 8, 20, 10, 0, tzinfo=UTC)


def _aggregate(suffix: str) -> tuple[Order, OrderVersion]:
    order_id = f"order-{suffix}"
    version_id = f"version-{suffix}"
    return (
        Order(
            order_id=order_id,
            source_inquiry_id=f"inquiry-{suffix}",
            created_at=_NOW,
            updated_at=_NOW,
        ),
        OrderVersion(
            order_version_id=version_id,
            order_id=order_id,
            version_number=1,
            created_at=_NOW,
            event_date=date(2026, 9, 1),
            time_window_text="12:00",
            location_text="Hamburg",
            guest_count_estimate=10,
            planning_mode="caterer_suggestion",
        ),
    )


def _context(
    order: Order, version: OrderVersion
) -> OrderVersionOperationalContextSnapshot:
    return OrderVersionOperationalContextSnapshot(
        order_version_id=version.order_version_id,
        order_id=order.order_id,
        recipient_company="Art.draw GmbH",
        recipient_name="Klara Morgen",
        recipient_phone="+4912345",
        delivery_address=None,
        created_at=_NOW,
        source="initial_inquiry_snapshot",
    )


def _forms() -> OrderDetailFormFields:
    return OrderDetailFormFields(
        csrf_input='<input name="_csrf_token" value="token">',
        print_confirm_command_fields={},
        effective_command_fields={},
        ready_command_fields="",
        cancel_command_fields="",
        version_command_fields="",
        payment_command_fields="",
    )


def test_delete_form_requires_exact_customer_name_and_is_superadmin_only() -> None:
    order, _version = _aggregate("ui")
    superadmin = OfficePageContext(current_user_role_label="Superadmin")

    html = _secondary_actions(
        order,
        _forms(),
        operational_pause={"active": False},
        delete_confirmation_name="Art.draw GmbH",
        context=superadmin,
    )

    assert 'action="/order/order-ui/delete"' in html
    assert "Art.draw GmbH" in html
    assert 'name="confirmation_name"' in html
    assert "Auftrag endgültig löschen" in html

    normal_user_html = _secondary_actions(
        order,
        _forms(),
        operational_pause={"active": False},
        delete_confirmation_name="Art.draw GmbH",
        context=OfficePageContext(current_user_role_label="Benutzer"),
    )
    assert 'action="/order/order-ui/delete"' not in normal_user_html


def test_in_memory_purge_removes_root_versions_and_operational_context() -> None:
    repo = InMemoryOrderRepository()
    order, version = _aggregate("memory")
    repo.save_order_with_initial_version(order, version, _context(order, version))

    purge_order_with_dependencies(repo, order.order_id)

    assert repo.get_order(order.order_id) is None
    assert repo.get_order_version(version.order_version_id) is None
    assert repo.list_order_versions(order.order_id) == []
    assert repo.get_operational_context(version.order_version_id) is None


def test_sqlite_purge_removes_owned_rows_and_restores_delete_guards(tmp_path) -> None:
    repo = SQLiteOrderRepository(tmp_path / "core.db")
    order, version = _aggregate("sqlite")
    repo.save_order_with_initial_version(order, version, _context(order, version))
    connection = repo._conn
    connection.execute(
        "CREATE TABLE purge_probe (probe_id TEXT PRIMARY KEY, order_id TEXT NOT NULL)"
    )
    connection.execute(
        "CREATE TRIGGER purge_probe_no_delete BEFORE DELETE ON purge_probe "
        "BEGIN SELECT RAISE(ABORT, 'probe is protected'); END"
    )
    connection.execute(
        "INSERT INTO purge_probe (probe_id, order_id) VALUES (?, ?)",
        ("probe-1", order.order_id),
    )
    connection.commit()

    purge_order_with_dependencies(repo, order.order_id)

    assert repo.get_order(order.order_id) is None
    assert repo.list_order_versions(order.order_id) == []
    assert (
        connection.execute(
            "SELECT 1 FROM purge_probe WHERE order_id = ?", (order.order_id,)
        ).fetchone()
        is None
    )
    trigger_names = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'trigger'"
        ).fetchall()
    }
    assert "purge_probe_no_delete" in trigger_names
    assert "trg_order_version_history_no_delete" in trigger_names

    second_order, second_version = _aggregate("guard")
    repo.save_order_with_initial_version(second_order, second_version)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        connection.execute(
            "DELETE FROM order_versions WHERE order_version_id = ?",
            (second_version.order_version_id,),
        )


def test_purge_unknown_order_is_non_destructive(tmp_path) -> None:
    repo = SQLiteOrderRepository(tmp_path / "core.db")
    order, version = _aggregate("kept")
    repo.save_order_with_initial_version(order, version)

    with pytest.raises(KeyError):
        purge_order_with_dependencies(repo, "missing-order")

    assert repo.get_order(order.order_id) == order
    assert repo.get_order_version(version.order_version_id) == version
