from __future__ import annotations

import base64
import http.cookiejar
import sqlite3
import threading
import urllib.error
import urllib.parse
import urllib.request
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote

import pytest

from catering_system.domain.inquiry import (
    PLANNING_MODES,
    Inquiry,
    InquiryOfferProjection,
    InquiryOfficeState,
    inquiry_shows_convert_accepted_button,
)
from catering_system.domain.inquiry_customer_snapshot import InquiryCustomerSnapshot
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
from catering_system.services.inquiry_service import InquiryService
from catering_system.ui.office_panel import OfficePanel, create_office_panel_server
from catering_system.ui.office_panel_contact_detail import render_kontakt_detail
from catering_system.ui.office_panel_http import csrf_token_for_password
from catering_system.ui.office_panel_inquiry_detail import (
    InquiryDetailFormFields,
    render_inquiry_detail,
)
from catering_system.ui.office_panel_views import OfficePageContext, _csrf_input
from tests.helpers.office_panel_context import legacy_office_context

_GERMAN_FORBIDDEN = "Ihre Berechtigung reicht für diese Aktion nicht aus."
_GERMAN_CSRF = "Ungültiger oder fehlender CSRF-Sicherheitstoken."


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


def _employee_jar(
    panel: PanelHarness,
    super_jar: http.cookiejar.CookieJar,
    *,
    username: str,
    password: str = "ReaderTemp1!",
    permissions: frozenset[str],
) -> http.cookiejar.CookieJar:
    _create_employee(
        panel,
        super_jar,
        username=username,
        password=password,
        role="USER",
        permissions=permissions,
    )
    return _login(panel, username=username, password=password)


def _employee_context(*permissions: str) -> OfficePageContext:
    return OfficePageContext(
        legacy_shared_access=False,
        employee_effective_permissions=frozenset(permissions),
        csrf_token="csrf-test",
    )


def _accepted_inquiry_state() -> tuple[Inquiry, InquiryOfficeState]:
    now = datetime(2026, 7, 14, 10, 0, tzinfo=UTC)
    inquiry = Inquiry(
        inquiry_id="22222222-2222-2222-2222-222222222222",
        event_date=date(2026, 10, 1),
        created_at=now,
        updated_at=now,
        inquiry_source="manual",
        crm_stage="Neue Anfrage",
        customer_linkage={},
        time_window_text="mittags",
        location_text="Hamburg",
        guest_count_estimate=25,
        planning_mode="caterer_suggestion",
        call_verification_required=False,
        call_verification_status="not_required",
        customer_snapshot=InquiryCustomerSnapshot(
            email="kunde@example.com",
            phone="+49301234567",
        ),
    )
    state = InquiryOfficeState(
        is_open=True,
        next_action="convert-accepted",
        offer=InquiryOfferProjection(
            offer_id="11111111-1111-1111-1111-111111111111",
            offer_version_id="33333333-3333-3333-3333-333333333331",
            commercial_state="Accepted",
            accepted_variant_id="44444444-4444-4444-4444-444444444441",
            acceptance_id="55555555-5555-5555-5555-555555555555",
        ),
    )
    assert inquiry_shows_convert_accepted_button(state)
    return inquiry, state


def _inquiry_detail_page(context: OfficePageContext) -> str:
    inquiry, state = _accepted_inquiry_state()
    detail = render_inquiry_detail(
        inquiry,
        [],
        state,
        (),
        forms=InquiryDetailFormFields(
            csrf_input=_csrf_input(context),
            primary_command_fields="",
            update_command_fields="",
        ),
        context=context,
    )
    return detail.body


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


@pytest.fixture()
def super_jar(employee_panel: PanelHarness) -> http.cookiejar.CookieJar:
    return _ready_superadmin(employee_panel)


@pytest.fixture()
def seeded_inquiry_id(
    employee_panel: PanelHarness, super_jar: http.cookiejar.CookieJar
) -> str:
    return _seed_inquiry(employee_panel.base, super_jar)


def _assert_post_forbidden(
    panel: PanelHarness,
    path: str,
    *,
    jar: http.cookiejar.CookieJar | None = None,
    data: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    patches: dict[str, str] | None = None,
) -> None:
    patch_targets = patches or {}
    with ExitStack() as stack:
        mocks = {
            name: stack.enter_context(patch(target, autospec=True))
            for name, target in patch_targets.items()
        }
        status, _url, body, _headers = _request(
            panel.base,
            path,
            method="POST",
            data=data or {},
            jar=jar,
            headers=headers,
        )
    assert status == 403
    assert _GERMAN_FORBIDDEN in body
    for mock in mocks.values():
        mock.assert_not_called()


@pytest.mark.parametrize(
    ("path", "data", "permissions", "patches", "username"),
    [
        (
            "/inquiry/new",
            {
                "event_date": "2026-09-01",
                "inquiry_source": "manual",
                "planning_mode": PLANNING_MODES[0],
            },
            frozenset({"inquiries.view"}),
            {
                "create_inquiry": "catering_system.ui.office_panel.OfficePanel.create_inquiry"
            },
            "denied.inquiry.new",
        ),
        (
            "/kontakt/test%40example.invalid/notizen",
            {"category": "Allgemein", "note_text": "Intern"},
            frozenset({"customers.view"}),
            {
                "add_contact_note": "catering_system.ui.office_panel.OfficePanel.add_contact_note"
            },
            "denied.contact.notes",
        ),
    ],
)
def test_auth2d2_post_denied_without_required_permission(
    employee_panel: PanelHarness,
    super_jar: http.cookiejar.CookieJar,
    path: str,
    data: dict[str, str],
    permissions: frozenset[str],
    patches: dict[str, str],
    username: str,
) -> None:
    jar = _employee_jar(
        employee_panel,
        super_jar,
        username=username,
        permissions=permissions,
    )
    _assert_post_forbidden(
        employee_panel,
        path,
        jar=jar,
        data={**data, "_csrf_token": _csrf(jar)},
        patches=patches,
    )


@pytest.mark.parametrize(
    ("action", "permissions", "patch_target"),
    [
        (
            "update",
            frozenset({"inquiries.view"}),
            "catering_system.ui.office_panel.OfficePanel.update_inquiry",
        ),
        (
            "contact-completion",
            frozenset({"inquiries.view"}),
            "catering_system.ui.office_panel.OfficePanel.complete_inquiry_contacts",
        ),
        (
            "fulfillment-mode",
            frozenset({"inquiries.view"}),
            "catering_system.ui.office_panel.OfficePanel.set_inquiry_fulfillment_mode",
        ),
        (
            "verify",
            frozenset({"inquiries.view"}),
            "catering_system.services.inquiry_service.InquiryService.verify_customer_by_call",
        ),
    ],
)
def test_auth2d2_inquiry_action_denied_without_edit_or_verify_permission(
    employee_panel: PanelHarness,
    super_jar: http.cookiejar.CookieJar,
    seeded_inquiry_id: str,
    action: str,
    permissions: frozenset[str],
    patch_target: str,
) -> None:
    jar = _employee_jar(
        employee_panel,
        super_jar,
        username=f"denied.{action}",
        permissions=permissions,
    )
    _assert_post_forbidden(
        employee_panel,
        f"/inquiry/{seeded_inquiry_id}/{action}",
        jar=jar,
        data={"_csrf_token": _csrf(jar)},
        patches={action: patch_target},
    )


def test_customer_addresses_requires_both_inquiries_view_and_customers_edit(
    employee_panel: PanelHarness,
    super_jar: http.cookiejar.CookieJar,
    seeded_inquiry_id: str,
) -> None:
    patch_target = (
        "catering_system.ui.office_panel.OfficePanel.set_inquiry_customer_addresses"
    )
    for username, permissions in (
        ("addresses.neither", frozenset({"inquiries.create"})),
        ("addresses.view.only", frozenset({"inquiries.view"})),
        ("addresses.edit.only", frozenset({"customers.edit"})),
    ):
        jar = _employee_jar(
            employee_panel,
            super_jar,
            username=username,
            permissions=permissions,
        )
        _assert_post_forbidden(
            employee_panel,
            f"/inquiry/{seeded_inquiry_id}/customer-addresses",
            jar=jar,
            data={"_csrf_token": _csrf(jar)},
            patches={"set_inquiry_customer_addresses": patch_target},
        )


def test_convert_requires_inquiries_view_and_orders_version_create(
    employee_panel: PanelHarness,
    super_jar: http.cookiejar.CookieJar,
    seeded_inquiry_id: str,
) -> None:
    patch_target = (
        "catering_system.ui.office_panel.OfficePanel.convert_inquiry_to_order"
    )
    for username, permissions in (
        ("convert.view.only", frozenset({"inquiries.view"})),
        ("convert.create.only", frozenset({"orders.version.create"})),
    ):
        jar = _employee_jar(
            employee_panel,
            super_jar,
            username=username,
            permissions=permissions,
        )
        _assert_post_forbidden(
            employee_panel,
            f"/inquiry/{seeded_inquiry_id}/convert",
            jar=jar,
            data={"_csrf_token": _csrf(jar)},
            patches={"convert_inquiry_to_order": patch_target},
        )


def test_convert_accepted_requires_offers_view_and_orders_version_create(
    employee_panel: PanelHarness,
    super_jar: http.cookiejar.CookieJar,
    seeded_inquiry_id: str,
) -> None:
    patch_target = (
        "catering_system.ui.office_panel.OfficePanel.convert_accepted_offer_for_inquiry"
    )
    for username, permissions in (
        ("convertacc.view.only", frozenset({"offers.view"})),
        ("convertacc.create.only", frozenset({"orders.version.create"})),
    ):
        jar = _employee_jar(
            employee_panel,
            super_jar,
            username=username,
            permissions=permissions,
        )
        _assert_post_forbidden(
            employee_panel,
            f"/inquiry/{seeded_inquiry_id}/convert-accepted",
            jar=jar,
            data={"_csrf_token": _csrf(jar)},
            patches={"convert_accepted_offer_for_inquiry": patch_target},
        )


def test_migration_basic_fallback_post_inquiry_new_works_without_employee_permission(
    migration_panel: PanelHarness,
) -> None:
    with patch.object(OfficePanel, "create_inquiry", autospec=True) as create_mock:
        create_mock.side_effect = lambda self, form: InquiryService(
            InMemoryInquiryRepository()
        ).create_inquiry(
            event_date=date(2026, 9, 1),
            inquiry_source="manual",
            crm_stage="Neue Anfrage",
            customer_linkage={},
            time_window_text="mittags",
            location_text="Hamburg",
            guest_count_estimate=10,
            planning_mode=PLANNING_MODES[0],
            call_verification_required=False,
            call_verification_status="not_required",
        )
        status, _url, _body, _headers = _request(
            migration_panel.base,
            "/inquiry/new",
            method="POST",
            data={
                "_csrf_token": csrf_token_for_password(migration_panel.password),
                "event_date": "2026-09-01",
                "inquiry_source": "manual",
                "planning_mode": PLANNING_MODES[0],
            },
            headers={"Authorization": _auth_header(migration_panel.password)},
        )
    assert status == 303
    create_mock.assert_called_once()


def test_migration_employee_without_inquiries_create_gets_403(
    migration_panel: PanelHarness,
) -> None:
    super_jar = _ready_superadmin(migration_panel)
    jar = _employee_jar(
        migration_panel,
        super_jar,
        username="migration.viewer",
        permissions=frozenset({"inquiries.view"}),
    )
    _assert_post_forbidden(
        migration_panel,
        "/inquiry/new",
        jar=jar,
        data={
            "_csrf_token": _csrf(jar),
            "event_date": "2026-09-01",
            "inquiry_source": "manual",
            "planning_mode": PLANNING_MODES[0],
        },
        patches={
            "create_inquiry": "catering_system.ui.office_panel.OfficePanel.create_inquiry"
        },
    )


def test_csrf_required_for_authorized_employee_post(
    employee_panel: PanelHarness,
    super_jar: http.cookiejar.CookieJar,
) -> None:
    jar = _employee_jar(
        employee_panel,
        super_jar,
        username="creator.without.csrf",
        permissions=frozenset({"inquiries.create"}),
    )
    with patch.object(OfficePanel, "create_inquiry", autospec=True) as create_mock:
        status, _url, body, _headers = _request(
            employee_panel.base,
            "/inquiry/new",
            method="POST",
            data={
                "event_date": "2026-09-01",
                "inquiry_source": "manual",
                "planning_mode": PLANNING_MODES[0],
            },
            jar=jar,
        )
    assert status == 403
    assert _GERMAN_CSRF in body
    assert _GERMAN_FORBIDDEN not in body
    create_mock.assert_not_called()


def test_valid_csrf_still_yields_permission_denied_without_required_permission(
    employee_panel: PanelHarness,
    super_jar: http.cookiejar.CookieJar,
) -> None:
    jar = _employee_jar(
        employee_panel,
        super_jar,
        username="viewer.with.csrf",
        permissions=frozenset({"inquiries.view"}),
    )
    with patch.object(OfficePanel, "create_inquiry", autospec=True) as create_mock:
        status, _url, body, _headers = _request(
            employee_panel.base,
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
    assert status == 403
    assert _GERMAN_FORBIDDEN in body
    assert _GERMAN_CSRF not in body
    create_mock.assert_not_called()


def test_inquiry_create_link_hidden_without_inquiries_create(
    employee_panel: PanelHarness,
    super_jar: http.cookiejar.CookieJar,
) -> None:
    jar = _employee_jar(
        employee_panel,
        super_jar,
        username="inquiry.reader.nav",
        permissions=frozenset({"inquiries.view", "queue.view"}),
    )
    status, _url, body, _headers = _request(employee_panel.base, "/", jar=jar)
    assert status == 200
    assert 'href="/inquiry/new"' not in body
    assert "+ Neue Anfrage" not in body


def test_contact_note_form_hidden_without_customers_edit() -> None:
    detail = {
        "contact_key": "intake:email:jk@example.invalid",
        "display_name": "JK-art",
        "email": "jk@example.invalid",
        "phone": "+4917642795029",
        "inquiries": [],
        "offers": [],
        "orders": [],
        "internal_notes": [],
    }
    page = render_kontakt_detail(
        detail,
        context=_employee_context("customers.view"),
    )
    assert "/notizen" not in page
    assert "Notiz speichern" not in page

    editable = render_kontakt_detail(
        detail,
        context=_employee_context("customers.view", "customers.edit"),
    )
    assert (
        f"/kontakt/{quote('intake:email:jk@example.invalid', safe='')}/notizen"
        in editable
    )
    assert "Notiz speichern" in editable


def test_convert_accepted_hidden_without_composite_permissions() -> None:
    body = _inquiry_detail_page(_employee_context("offers.view"))
    assert "convert-accepted" not in body
    assert "Angenommenes Angebot in Auftrag überführen" not in body

    body_with_create = _inquiry_detail_page(
        _employee_context("orders.version.create"),
    )
    assert "convert-accepted" not in body_with_create

    body_allowed = _inquiry_detail_page(
        _employee_context("offers.view", "orders.version.create"),
    )
    assert "convert-accepted" in body_allowed
    assert "Angenommenes Angebot in Auftrag überführen" in body_allowed


def test_legacy_office_context_retains_convert_accepted_control() -> None:
    body = _inquiry_detail_page(legacy_office_context(csrf_token="csrf"))
    assert "convert-accepted" in body
    assert "Angenommenes Angebot in Auftrag überführen" in body
