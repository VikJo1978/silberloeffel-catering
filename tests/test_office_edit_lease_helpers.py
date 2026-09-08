from __future__ import annotations

import sqlite3
from types import SimpleNamespace
from typing import Any

from catering_system.repositories.sqlite_office_edit_lease_repository import (
    SQLiteOfficeEditLeaseRepository,
)
from catering_system.ui import office_panel_multiuser as multiuser


def _auth(account_id: str, display_name: str, *permissions: str) -> Any:
    account = SimpleNamespace(id=account_id, display_name=display_name)
    employee = SimpleNamespace(
        account=account,
        effective_permissions=frozenset(permissions),
    )
    return SimpleNamespace(
        kind="employee",
        employee=employee,
        legacy_shared_access=False,
        csrf_token="csrf-test",
    )


def test_route_and_identity_helpers() -> None:
    detail = multiuser._detail_record("/inquiry/inq-1?tab=kontakt")
    assert detail == ("inquiry", "inq-1")
    assert multiuser._detail_record("/kontakt/contact-1") is None
    assert multiuser._detail_record("/order/order-1/extra") is None

    post = multiuser._post_record(["offer", "offer-1", "status"])
    assert post == ("offer", "offer-1")
    send = ["order", "order-1", "confirmation-document", "send"]
    assert multiuser._post_record(send) == ("order", "order-1")
    assert multiuser._post_record(["order", "order-1"]) is None

    takeover = ["work-lease", "order", "order-1", "takeover"]
    route = multiuser._lease_route(takeover)
    assert route == ("order", "order-1", "takeover")
    invalid = ["work-lease", "order", "order-1", "invalid"]
    assert multiuser._lease_route(invalid) is None
    assert multiuser._lease_route(["order", "order-1"]) is None

    assert multiuser._employee_actor(None) is None
    assert multiuser._employee_actor(SimpleNamespace(kind="basic")) is None
    missing = SimpleNamespace(
        kind="employee",
        employee=None,
        legacy_shared_access=False,
    )
    assert multiuser._employee_actor(missing) is None

    legacy = _auth("anna", "Anna Bromm", "inquiries.edit")
    legacy.legacy_shared_access = True
    assert multiuser._employee_actor(legacy) is None

    employee = _auth("anna", "Anna Bromm", "orders.pause")
    actor = multiuser._employee_actor(employee)
    assert actor is not None
    assert actor[0] == "anna"
    assert actor[1] == "Anna Bromm"
    assert multiuser._can_coordinate(employee, "order") is True

    viewer = _auth("viewer", "Viewer", "orders.view")
    assert multiuser._can_coordinate(viewer, "order") is False
    assert multiuser._can_coordinate(None, "order") is False
    assert multiuser._record_url("inquiry", "a b/x") == "/inquiry/a%20b%2Fx"


def test_repository_wiring_and_owned_banner() -> None:
    assert multiuser._lease_repository(None) is None

    bad_repo = SimpleNamespace(_conn="not-sqlite")
    bad_service = SimpleNamespace(repository=bad_repo)
    assert multiuser._lease_repository(bad_service) is None

    connection = sqlite3.connect(":memory:")
    auth_repo = SimpleNamespace(_conn=connection)
    auth_service = SimpleNamespace(repository=auth_repo)
    wired = multiuser._lease_repository(auth_service)
    assert isinstance(wired, SQLiteOfficeEditLeaseRepository)

    claim = wired.claim_or_observe(
        "inquiry",
        "inq-own",
        holder_account_id="anna",
        holder_display_name="Anna Bromm",
    )
    banner = multiuser._lease_banner(claim, csrf_token='<csrf&"token>')
    assert "In Bearbeitung durch Sie." in banner
    assert "Bearbeitung beenden" in banner
    assert "/work-lease/inquiry/inq-own/release" in banner
    assert "&lt;csrf&amp;&quot;token&gt;" in banner

    class DummyHandler:
        pass

    decorated = multiuser.add_edit_lease_coordination(DummyHandler, None)
    assert decorated is DummyHandler
