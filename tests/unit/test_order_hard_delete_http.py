from __future__ import annotations

import http.cookiejar
import sqlite3
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from catering_system.domain.order import Order, OrderVersion
from catering_system.domain.order_operational_context import (
    OrderVersionOperationalContextSnapshot,
)
from catering_system.repositories.in_memory_inquiry_repository import (
    InMemoryInquiryRepository,
)
from catering_system.repositories.in_memory_order_repository import (
    InMemoryOrderRepository,
)
from catering_system.repositories.sqlite_employee_auth_repository import (
    SQLiteEmployeeAuthRepository,
)
from catering_system.services.employee_auth_service import EmployeeAuthService
from catering_system.ui.office_panel import create_office_panel_server

_NOW = datetime(2026, 8, 20, 10, 0, tzinfo=UTC)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@pytest.fixture()
def panel(tmp_path: Path):
    auth_connection = sqlite3.connect(
        str(tmp_path / "auth.db"), check_same_thread=False
    )
    auth_repo = SQLiteEmployeeAuthRepository.from_connection(auth_connection)
    auth_service = EmployeeAuthService(auth_repo, now=lambda: _NOW)
    auth_service.bootstrap_superadmin(
        username="viktor.admin",
        display_name="Viktor Admin",
        password="TempPassw0rd!",
        metadata={"seed": "order-delete-http"},
    )
    orders = InMemoryOrderRepository()
    server = create_office_panel_server(
        InMemoryInquiryRepository(),
        orders,
        "shared-office-password",
        host="127.0.0.1",
        port=0,
        auth_mode="employee",
        auth_service=auth_service,
        secure_cookie=False,
        ui_version="v2",
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    base = f"http://{host}:{port}"
    try:
        yield base, orders, auth_service
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        auth_repo.close()


def _request(
    base: str,
    path: str,
    *,
    method: str = "GET",
    data: dict[str, str] | None = None,
    jar: http.cookiejar.CookieJar | None = None,
) -> tuple[int, str, str]:
    cookie_jar = jar if jar is not None else http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(
        _NoRedirect,
        urllib.request.HTTPCookieProcessor(cookie_jar),
    )
    payload = urllib.parse.urlencode(data).encode() if data is not None else None
    request = urllib.request.Request(f"{base}{path}", data=payload, method=method)
    try:
        with opener.open(request) as response:
            return response.status, response.url, response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.geturl(), exc.read().decode("utf-8")


def _cookie(jar: http.cookiejar.CookieJar, name: str) -> str:
    for cookie in jar:
        if cookie.name == name:
            return cookie.value
    raise AssertionError(f"missing cookie {name}")


def _login(base: str, username: str, password: str) -> http.cookiejar.CookieJar:
    jar = http.cookiejar.CookieJar()
    status, _url, _body = _request(
        base,
        "/login",
        method="POST",
        data={"username": username, "password": password, "next": "/"},
        jar=jar,
    )
    assert status == 303
    return jar


def _ready_superadmin(
    base: str, service: EmployeeAuthService
) -> http.cookiejar.CookieJar:
    jar = _login(base, "viktor.admin", "TempPassw0rd!")
    employee = service.authenticate_session(_cookie(jar, "sl_employee_session"))
    service.change_password(
        employee,
        current_password="TempPassw0rd!",
        new_password="ChangedTemp1!",
    )
    return _login(base, "viktor.admin", "ChangedTemp1!")


def _employee(
    base: str,
    service: EmployeeAuthService,
    *,
    username: str,
    permissions: set[str],
) -> http.cookiejar.CookieJar:
    super_jar = _ready_superadmin(base, service)
    actor = service.authenticate_session(_cookie(super_jar, "sl_employee_session"))
    service.create_account(
        actor,
        username=username,
        display_name=username,
        password="EmployeeTemp1!",
        role="USER",
        explicit_permissions=permissions,
        must_change_password=False,
    )
    return _login(base, username, "EmployeeTemp1!")


def _seed_order(repo: InMemoryOrderRepository, suffix: str) -> str:
    order_id = f"order-{suffix}"
    version_id = f"version-{suffix}"
    order = Order(
        order_id=order_id,
        source_inquiry_id=f"inquiry-{suffix}",
        created_at=_NOW,
        updated_at=_NOW,
    )
    version = OrderVersion(
        order_version_id=version_id,
        order_id=order_id,
        version_number=1,
        created_at=_NOW,
        event_date=date(2026, 9, 1),
        time_window_text="12:00",
        location_text="Hamburg",
        guest_count_estimate=10,
        planning_mode="caterer_suggestion",
    )
    context = OrderVersionOperationalContextSnapshot(
        order_version_id=version_id,
        order_id=order_id,
        recipient_company="Art.draw GmbH",
        recipient_name="Klara Morgen",
        recipient_phone="+4912345",
        delivery_address=None,
        created_at=_NOW,
        source="initial_inquiry_snapshot",
    )
    repo.save_order_with_initial_version(order, version, context)
    return order_id


def _delete(
    base: str,
    order_id: str,
    jar: http.cookiejar.CookieJar,
    confirmation_name: str,
) -> tuple[int, str, str]:
    return _request(
        base,
        f"/order/{order_id}/delete",
        method="POST",
        data={
            "_csrf_token": _cookie(jar, "sl_employee_csrf"),
            "confirmation_name": confirmation_name,
        },
        jar=jar,
    )


def test_delete_requires_orders_delete_permission(panel) -> None:
    base, orders, service = panel
    order_id = _seed_order(orders, "forbidden")
    jar = _employee(
        base,
        service,
        username="delete.denied",
        permissions={"orders.view"},
    )

    status, _url, body = _delete(base, order_id, jar, "Art.draw GmbH")

    assert status == 403
    assert "Ihre Berechtigung reicht für diese Aktion nicht aus." in body
    assert orders.get_order(order_id) is not None


def test_delete_rejects_wrong_confirmation_name(panel) -> None:
    base, orders, service = panel
    order_id = _seed_order(orders, "mismatch")
    jar = _employee(
        base,
        service,
        username="delete.mismatch",
        permissions={"orders.view", "orders.delete"},
    )

    status, _url, body = _delete(base, order_id, jar, "Art Draw GmbH")

    assert status == 400
    assert "Kunden-/Firmenname stimmt nicht überein" in body
    assert orders.get_order(order_id) is not None


def test_delete_with_permission_and_exact_name_purges_order(panel) -> None:
    base, orders, service = panel
    order_id = _seed_order(orders, "success")
    jar = _employee(
        base,
        service,
        username="delete.allowed",
        permissions={"orders.view", "orders.delete"},
    )

    status, url, _body = _delete(base, order_id, jar, "Art.draw GmbH")

    assert status == 303
    assert url.endswith("/orders")
    assert orders.get_order(order_id) is None
    assert orders.list_order_versions(order_id) == []
