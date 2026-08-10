from __future__ import annotations

import base64
import http.cookiejar
import sqlite3
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from catering_system.domain.inquiry import PLANNING_MODES
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
from catering_system.ui.office_panel import OfficePanel, create_office_panel_server
from catering_system.ui.office_panel_authz import can_access


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass
class PanelHarness:
    base: str
    server: object
    thread: threading.Thread
    service: EmployeeAuthService
    repo: SQLiteEmployeeAuthRepository
    password: str


def _auth_header(password: str) -> str:
    return "Basic " + base64.b64encode(f"office:{password}".encode()).decode()


def _cookie_value(jar: http.cookiejar.CookieJar, name: str) -> str:
    for cookie in jar:
        if cookie.name == name:
            return cookie.value
    raise AssertionError(f"missing cookie {name}")


def _csrf(jar: http.cookiejar.CookieJar) -> str:
    return _cookie_value(jar, "sl_employee_csrf")


def _request(
    base: str,
    path: str,
    *,
    method: str = "GET",
    data: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    jar: http.cookiejar.CookieJar | None = None,
) -> tuple[int, str, str, object]:
    cookie_jar = jar if jar is not None else http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(
        _NoRedirect,
        urllib.request.HTTPCookieProcessor(cookie_jar),
    )
    payload = None
    if data is not None:
        payload = urllib.parse.urlencode(data).encode()
    request = urllib.request.Request(
        f"{base}{path}",
        data=payload,
        method=method,
    )
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    try:
        with opener.open(request) as response:
            return (
                response.status,
                response.url,
                response.read().decode("utf-8"),
                response.headers,
            )
    except urllib.error.HTTPError as exc:
        return exc.code, exc.geturl(), exc.read().decode("utf-8"), exc.headers


def _create_panel(
    tmp_path: Path,
    *,
    auth_mode: str,
    password: str = "shared-office-password",
) -> PanelHarness:
    db = tmp_path / "core.db"
    connection = sqlite3.connect(str(db), check_same_thread=False)
    repo = SQLiteEmployeeAuthRepository.from_connection(connection)
    service = EmployeeAuthService(
        repo, now=lambda: datetime(2026, 8, 1, 9, 0, tzinfo=UTC)
    )
    service.bootstrap_superadmin(
        username="viktor.admin",
        display_name="Viktor Johanson",
        password="TempPassw0rd!",
        metadata={"seed": "office-panel"},
    )
    server = create_office_panel_server(
        InMemoryInquiryRepository(),
        InMemoryOrderRepository(),
        password,
        host="127.0.0.1",
        port=0,
        auth_mode=auth_mode,
        auth_service=service,
        secure_cookie=False,
        ui_version="v2",
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    return PanelHarness(
        base=f"http://{host}:{port}",
        server=server,
        thread=thread,
        service=service,
        repo=repo,
        password=password,
    )


def _shutdown(panel: PanelHarness) -> None:
    panel.server.shutdown()
    panel.server.server_close()
    panel.thread.join(timeout=5)
    panel.repo.close()


def _login(
    panel: PanelHarness, *, username: str, password: str
) -> http.cookiejar.CookieJar:
    jar = http.cookiejar.CookieJar()
    status, _url, _body, _headers = _request(
        panel.base,
        "/login",
        method="POST",
        data={"username": username, "password": password, "next": "/"},
        jar=jar,
    )
    assert status == 303
    return jar


def _ready_superadmin(panel: PanelHarness) -> http.cookiejar.CookieJar:
    jar = _login(panel, username="viktor.admin", password="TempPassw0rd!")
    employee = panel.service.authenticate_session(
        _cookie_value(jar, "sl_employee_session")
    )
    panel.service.change_password(
        employee,
        current_password="TempPassw0rd!",
        new_password="ChangedTemp1!",
    )
    return _login(panel, username="viktor.admin", password="ChangedTemp1!")


def _create_employee(
    panel: PanelHarness,
    super_jar: http.cookiejar.CookieJar,
    *,
    username: str,
    password: str,
    role: str,
    permissions: frozenset[str] | None = None,
) -> str:
    super_employee = panel.service.authenticate_session(
        _cookie_value(super_jar, "sl_employee_session")
    )
    account = panel.service.create_account(
        super_employee,
        username=username,
        display_name=username,
        password=password,
        role=role,
        explicit_permissions=set(permissions) if permissions is not None else None,
        must_change_password=False,
    )
    return account.id


def _seed_inquiry(panel_base: str, jar: http.cookiejar.CookieJar) -> str:
    status, _url, _body, _headers = _request(
        panel_base,
        "/inquiry/new",
        method="POST",
        data={
            "_csrf_token": _csrf(jar),
            "event_date": "2026-09-01",
            "inquiry_source": "manual",
            "planning_mode": PLANNING_MODES[0],
        },
        jar=jar,
    )
    assert status == 303
    inquiry_id = _url.rsplit("/", 1)[-1]
    return inquiry_id


@pytest.fixture()
def employee_panel(tmp_path: Path):
    panel = _create_panel(tmp_path, auth_mode="employee")
    yield panel
    _shutdown(panel)


@pytest.fixture()
def migration_panel(tmp_path: Path):
    panel = _create_panel(tmp_path, auth_mode="migration")
    yield panel
    _shutdown(panel)


def test_superadmin_can_open_protected_get_routes(employee_panel: PanelHarness) -> None:
    jar = _ready_superadmin(employee_panel)
    for path in (
        "/",
        "/anfragen",
        "/angebote",
        "/kontakte",
        "/kalender",
        "/auftraege",
        "/gerichte",
        "/settings/users",
    ):
        status, _url, _body, _headers = _request(employee_panel.base, path, jar=jar)
        assert status == 200, path


def test_user_with_inquiries_view_can_open_anfragen(
    employee_panel: PanelHarness,
) -> None:
    super_jar = _ready_superadmin(employee_panel)
    _create_employee(
        employee_panel,
        super_jar,
        username="inquiry.reader",
        password="ReaderTemp1!",
        role="USER",
        permissions=frozenset({"inquiries.view"}),
    )
    jar = _login(employee_panel, username="inquiry.reader", password="ReaderTemp1!")
    status, _url, body, _headers = _request(employee_panel.base, "/anfragen", jar=jar)
    assert status == 200
    assert "Anfragen" in body


def test_user_without_inquiries_view_gets_german_403(
    employee_panel: PanelHarness,
) -> None:
    super_jar = _ready_superadmin(employee_panel)
    _create_employee(
        employee_panel,
        super_jar,
        username="no.inquiries",
        password="ReaderTemp1!",
        role="USER",
        permissions=frozenset({"orders.view"}),
    )
    jar = _login(employee_panel, username="no.inquiries", password="ReaderTemp1!")
    status, _url, body, _headers = _request(employee_panel.base, "/anfragen", jar=jar)
    assert status == 403
    assert "Ihre Berechtigung reicht für diese Aktion nicht aus." in body


def test_direct_inquiry_detail_denied_without_inquiries_view(
    employee_panel: PanelHarness,
) -> None:
    super_jar = _ready_superadmin(employee_panel)
    inquiry_id = _seed_inquiry(employee_panel.base, super_jar)
    _create_employee(
        employee_panel,
        super_jar,
        username="order.only",
        password="ReaderTemp1!",
        role="USER",
        permissions=frozenset({"orders.view"}),
    )
    jar = _login(employee_panel, username="order.only", password="ReaderTemp1!")
    status, _url, body, _headers = _request(
        employee_panel.base, f"/inquiry/{inquiry_id}", jar=jar
    )
    assert status == 403
    assert "Ihre Berechtigung reicht" in body


def test_viewer_with_orders_view_can_read_order_pages(
    employee_panel: PanelHarness,
) -> None:
    super_jar = _ready_superadmin(employee_panel)
    _create_employee(
        employee_panel,
        super_jar,
        username="viewer.orders",
        password="ViewerTemp1!",
        role="VIEWER",
        permissions=frozenset({"orders.view"}),
    )
    jar = _login(employee_panel, username="viewer.orders", password="ViewerTemp1!")
    status, _url, body, _headers = _request(employee_panel.base, "/auftraege", jar=jar)
    assert status == 200


def test_viewer_does_not_see_operational_order_buttons(
    employee_panel: PanelHarness,
) -> None:
    super_jar = _ready_superadmin(employee_panel)
    _create_employee(
        employee_panel,
        super_jar,
        username="viewer.readonly",
        password="ViewerTemp1!",
        role="VIEWER",
        permissions=frozenset({"orders.view"}),
    )
    jar = _login(employee_panel, username="viewer.readonly", password="ViewerTemp1!")
    status, _url, body, _headers = _request(employee_panel.base, "/auftraege", jar=jar)
    assert status == 200
    assert "Küchendruck starten" not in body
    assert "Auftrag stornieren" not in body


def test_pdf_denied_without_permission_and_renderer_not_called(
    employee_panel: PanelHarness,
) -> None:
    super_jar = _ready_superadmin(employee_panel)
    _create_employee(
        employee_panel,
        super_jar,
        username="no.pdf",
        password="ReaderTemp1!",
        role="USER",
        permissions=frozenset({"offers.view"}),
    )
    jar = _login(employee_panel, username="no.pdf", password="ReaderTemp1!")
    with patch.object(
        OfficePanel,
        "offer_document_pdf",
        autospec=True,
    ) as pdf_mock:
        status, _url, body, _headers = _request(
            employee_panel.base,
            "/offer/test-offer/offer-document/pdf?offer_version_id=v1",
            jar=jar,
        )
    assert status == 403
    assert "Ihre Berechtigung reicht" in body
    pdf_mock.assert_not_called()


def test_catalog_list_allowed_with_catalog_view(
    employee_panel: PanelHarness,
) -> None:
    super_jar = _ready_superadmin(employee_panel)
    _create_employee(
        employee_panel,
        super_jar,
        username="catalog.reader",
        password="ReaderTemp1!",
        role="USER",
        permissions=frozenset({"catalog.view"}),
    )
    jar = _login(employee_panel, username="catalog.reader", password="ReaderTemp1!")
    status, _url, body, _headers = _request(employee_panel.base, "/gerichte", jar=jar)
    assert status == 200


def test_catalog_edit_form_denied_without_catalog_edit(
    employee_panel: PanelHarness,
) -> None:
    super_jar = _ready_superadmin(employee_panel)
    _create_employee(
        employee_panel,
        super_jar,
        username="catalog.reader2",
        password="ReaderTemp1!",
        role="USER",
        permissions=frozenset({"catalog.view"}),
    )
    jar = _login(employee_panel, username="catalog.reader2", password="ReaderTemp1!")
    status, _url, body, _headers = _request(
        employee_panel.base, "/gerichte/new", jar=jar
    )
    assert status == 403


def test_dashboard_ok_without_calendar_view_and_widget_absent(
    employee_panel: PanelHarness,
) -> None:
    super_jar = _ready_superadmin(employee_panel)
    _create_employee(
        employee_panel,
        super_jar,
        username="queue.only",
        password="ReaderTemp1!",
        role="USER",
        permissions=frozenset({"queue.view"}),
    )
    jar = _login(employee_panel, username="queue.only", password="ReaderTemp1!")
    status, _url, body, _headers = _request(employee_panel.base, "/", jar=jar)
    assert status == 200
    assert 'id="diese-woche"' not in body
    assert "Nächste Veranstaltungen" not in body


def test_direct_kalender_denied_without_calendar_view(
    employee_panel: PanelHarness,
) -> None:
    super_jar = _ready_superadmin(employee_panel)
    _create_employee(
        employee_panel,
        super_jar,
        username="queue.only2",
        password="ReaderTemp1!",
        role="USER",
        permissions=frozenset({"queue.view"}),
    )
    jar = _login(employee_panel, username="queue.only2", password="ReaderTemp1!")
    status, _url, body, _headers = _request(employee_panel.base, "/kalender", jar=jar)
    assert status == 403


def test_migration_basic_fallback_retains_business_get_access(
    migration_panel: PanelHarness,
) -> None:
    status, _url, body, _headers = _request(
        migration_panel.base,
        "/anfragen",
        headers={"Authorization": _auth_header(migration_panel.password)},
    )
    assert status == 200


def test_migration_basic_fallback_denied_for_settings_users(
    migration_panel: PanelHarness,
) -> None:
    status, _url, body, _headers = _request(
        migration_panel.base,
        "/settings/users",
        headers={"Authorization": _auth_header(migration_panel.password)},
    )
    assert status == 403


def test_unauthenticated_get_redirects_to_login(employee_panel: PanelHarness) -> None:
    status, _url, _body, headers = _request(employee_panel.base, "/anfragen")
    assert status == 303
    assert headers["Location"].startswith("/login")


def test_sidebar_shows_only_permitted_sections(employee_panel: PanelHarness) -> None:
    super_jar = _ready_superadmin(employee_panel)
    _create_employee(
        employee_panel,
        super_jar,
        username="inquiry.only.nav",
        password="ReaderTemp1!",
        role="USER",
        permissions=frozenset({"inquiries.view"}),
    )
    jar = _login(employee_panel, username="inquiry.only.nav", password="ReaderTemp1!")
    status, _url, body, _headers = _request(employee_panel.base, "/anfragen", jar=jar)
    assert status == 200
    assert "Anfragen" in body
    assert 'href="/angebote"' not in body
    assert 'href="/auftraege"' not in body


def test_hidden_nav_item_still_denied_by_direct_url(
    employee_panel: PanelHarness,
) -> None:
    super_jar = _ready_superadmin(employee_panel)
    _create_employee(
        employee_panel,
        super_jar,
        username="inquiry.only.direct",
        password="ReaderTemp1!",
        role="USER",
        permissions=frozenset({"inquiries.view"}),
    )
    jar = _login(
        employee_panel, username="inquiry.only.direct", password="ReaderTemp1!"
    )
    status, _url, body, _headers = _request(employee_panel.base, "/angebote", jar=jar)
    assert status == 403


def test_inquiry_create_link_hidden_without_permission(
    employee_panel: PanelHarness,
) -> None:
    super_jar = _ready_superadmin(employee_panel)
    _create_employee(
        employee_panel,
        super_jar,
        username="inquiry.reader.nav",
        password="ReaderTemp1!",
        role="USER",
        permissions=frozenset({"inquiries.view", "queue.view"}),
    )
    jar = _login(employee_panel, username="inquiry.reader.nav", password="ReaderTemp1!")
    status, _url, body, _headers = _request(employee_panel.base, "/", jar=jar)
    assert status == 200
    assert 'href="/inquiry/new"' not in body


def test_catalog_edit_link_hidden_without_catalog_edit(
    employee_panel: PanelHarness,
) -> None:
    super_jar = _ready_superadmin(employee_panel)
    _create_employee(
        employee_panel,
        super_jar,
        username="catalog.view.nav",
        password="ReaderTemp1!",
        role="USER",
        permissions=frozenset({"catalog.view"}),
    )
    jar = _login(employee_panel, username="catalog.view.nav", password="ReaderTemp1!")
    status, _url, body, _headers = _request(employee_panel.base, "/gerichte", jar=jar)
    assert status == 200
    assert 'href="/gerichte/new"' not in body


def test_csrf_still_required_for_existing_post_routes(
    employee_panel: PanelHarness,
) -> None:
    jar = _ready_superadmin(employee_panel)
    status, _url, body, _headers = _request(
        employee_panel.base,
        "/logout",
        method="POST",
        data={},
        jar=jar,
    )
    assert status == 403
    assert "CSRF-Sicherheitstoken" in body


def test_office_page_context_can_matches_authz_helper() -> None:
    from catering_system.ui.office_panel_views import OfficePageContext

    context = OfficePageContext(
        legacy_shared_access=False,
        employee_effective_permissions=frozenset({"inquiries.view"}),
    )
    assert context.can("inquiries.view") is True
    assert context.can("orders.view") is False
    assert context.can("unknown.permission") is False
    assert can_access(None, "inquiries.view") is False


def test_denied_anfragen_does_not_fetch_rueckruf_count(
    employee_panel: PanelHarness,
) -> None:
    super_jar = _ready_superadmin(employee_panel)
    _create_employee(
        employee_panel,
        super_jar,
        username="orders.only",
        password="ReaderTemp1!",
        role="USER",
        permissions=frozenset({"orders.view"}),
    )
    jar = _login(employee_panel, username="orders.only", password="ReaderTemp1!")
    with patch(
        "catering_system.ui.office_panel_http.fetch_rueckruf_count",
        autospec=True,
    ) as count_mock:
        status, _url, body, _headers = _request(
            employee_panel.base, "/anfragen", jar=jar
        )
    assert status == 403
    assert "Ihre Berechtigung reicht" in body
    count_mock.assert_not_called()


def test_denied_offer_detail_does_not_fetch_rueckruf_count(
    employee_panel: PanelHarness,
) -> None:
    super_jar = _ready_superadmin(employee_panel)
    _create_employee(
        employee_panel,
        super_jar,
        username="orders.only.offer",
        password="ReaderTemp1!",
        role="USER",
        permissions=frozenset({"orders.view"}),
    )
    jar = _login(employee_panel, username="orders.only.offer", password="ReaderTemp1!")
    with patch(
        "catering_system.ui.office_panel_http.fetch_rueckruf_count",
        autospec=True,
    ) as count_mock:
        status, _url, body, _headers = _request(
            employee_panel.base, "/offer/test-offer", jar=jar
        )
    assert status == 403
    count_mock.assert_not_called()


def test_denied_pdf_does_not_fetch_rueckruf_count_or_renderer(
    employee_panel: PanelHarness,
) -> None:
    super_jar = _ready_superadmin(employee_panel)
    _create_employee(
        employee_panel,
        super_jar,
        username="offers.view.only",
        password="ReaderTemp1!",
        role="USER",
        permissions=frozenset({"offers.view"}),
    )
    jar = _login(employee_panel, username="offers.view.only", password="ReaderTemp1!")
    with (
        patch(
            "catering_system.ui.office_panel_http.fetch_rueckruf_count",
            autospec=True,
        ) as count_mock,
        patch.object(
            OfficePanel,
            "offer_document_pdf",
            autospec=True,
        ) as pdf_mock,
    ):
        status, _url, body, _headers = _request(
            employee_panel.base,
            "/offer/test-offer/offer-document/pdf?offer_version_id=v1",
            jar=jar,
        )
    assert status == 403
    count_mock.assert_not_called()
    pdf_mock.assert_not_called()


def test_allowed_anfragen_still_fetches_rueckruf_count_for_badge(
    employee_panel: PanelHarness,
) -> None:
    super_jar = _ready_superadmin(employee_panel)
    _create_employee(
        employee_panel,
        super_jar,
        username="inquiry.reader.badge",
        password="ReaderTemp1!",
        role="USER",
        permissions=frozenset({"inquiries.view"}),
    )
    jar = _login(
        employee_panel, username="inquiry.reader.badge", password="ReaderTemp1!"
    )
    with patch(
        "catering_system.ui.office_panel_http.fetch_rueckruf_count",
        autospec=True,
        return_value=3,
    ) as count_mock:
        status, _url, body, _headers = _request(
            employee_panel.base, "/anfragen", jar=jar
        )
    assert status == 200
    count_mock.assert_called_once()


def test_aufgaben_hidden_without_queue_view(employee_panel: PanelHarness) -> None:
    super_jar = _ready_superadmin(employee_panel)
    _create_employee(
        employee_panel,
        super_jar,
        username="inquiry.only.tasks",
        password="ReaderTemp1!",
        role="USER",
        permissions=frozenset({"inquiries.view"}),
    )
    jar = _login(employee_panel, username="inquiry.only.tasks", password="ReaderTemp1!")
    status, _url, body, _headers = _request(employee_panel.base, "/anfragen", jar=jar)
    assert status == 200
    assert 'href="/aufgaben"' not in body


def test_aufgaben_visible_with_queue_view_without_inquiries_view(
    employee_panel: PanelHarness,
) -> None:
    super_jar = _ready_superadmin(employee_panel)
    _create_employee(
        employee_panel,
        super_jar,
        username="queue.only.tasks",
        password="ReaderTemp1!",
        role="USER",
        permissions=frozenset({"queue.view"}),
    )
    jar = _login(employee_panel, username="queue.only.tasks", password="ReaderTemp1!")
    status, _url, body, _headers = _request(employee_panel.base, "/", jar=jar)
    assert status == 200
    assert 'href="/aufgaben"' in body
    assert 'href="/anfragen"' not in body


def test_aufgaben_direct_url_requires_queue_view(
    employee_panel: PanelHarness,
) -> None:
    super_jar = _ready_superadmin(employee_panel)
    _create_employee(
        employee_panel,
        super_jar,
        username="inquiry.only.tasks.direct",
        password="ReaderTemp1!",
        role="USER",
        permissions=frozenset({"inquiries.view"}),
    )
    jar = _login(
        employee_panel, username="inquiry.only.tasks.direct", password="ReaderTemp1!"
    )
    status, _url, body, _headers = _request(employee_panel.base, "/aufgaben", jar=jar)
    assert status == 403
