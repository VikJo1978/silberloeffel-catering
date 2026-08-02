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

import pytest

from catering_system.domain.employee_auth import (
    PERMISSION_REGISTRY,
    PERMISSION_SET,
    ROLE_DEFAULT_GRANTS,
    VIEW_PERMISSION_SET,
    effective_permissions,
    ensure_permissions_within_role,
    role_ceiling,
    validate_permission_code,
)
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
from catering_system.ui.office_panel_http import csrf_token_for_password
from catering_system.ui.office_panel_settings_users import PERMISSION_LABELS
from catering_system.ui.office_panel_views import OfficePageContext
from tests.helpers.office_panel_context import legacy_office_context
from tests.helpers.order_seed import seed_order

_GERMAN_FORBIDDEN = "Ihre Berechtigung reicht für diese Aktion nicht aus."
_GERMAN_CSRF = "Ungültiger oder fehlender CSRF-Sicherheitstoken."
_ORDER_ID = "66666666-6666-6666-6666-666666666666"
_VERSION_ID = "33333333-3333-4333-8333-333333333331"
_INQUIRY_ID = "22222222-2222-2222-2222-222222222222"
_OFFER_ID = "11111111-1111-4111-8111-111111111111"

_ORDER_POST_ACTIONS: tuple[tuple[str, str, str], ...] = (
    ("version", "orders.version.create", "create_version"),
    ("print-confirm", "orders.print.confirm", "confirm_kitchen_print"),
    ("effective", "orders.effective.set", "make_order_version_effective"),
    ("ready", "orders.ready.release", "request_ready_to_send"),
    ("pause", "orders.pause", "pause_order"),
    ("resume", "orders.pause", "resume_order"),
    ("cancel", "orders.cancel", "cancel_order"),
    ("payment-reminder", "orders.payment.reminder", "save_payment_reminder"),
)

_PATCH_TARGETS: dict[str, str] = {
    "create_version": "catering_system.ui.office_panel.OfficePanel.create_version",
    "confirm_kitchen_print": (
        "catering_system.services.operational_core_service."
        "OperationalCoreService.confirm_kitchen_print"
    ),
    "make_order_version_effective": (
        "catering_system.services.operational_core_service."
        "OperationalCoreService.make_order_version_effective"
    ),
    "request_ready_to_send": (
        "catering_system.services.operational_core_service."
        "OperationalCoreService.request_ready_to_send"
    ),
    "pause_order": "catering_system.ui.office_panel.OfficePanel.pause_order",
    "resume_order": "catering_system.ui.office_panel.OfficePanel.resume_order",
    "cancel_order": (
        "catering_system.services.operational_core_service."
        "OperationalCoreService.cancel_order"
    ),
    "save_payment_reminder": (
        "catering_system.ui.office_panel.OfficePanel.save_payment_reminder"
    ),
    "prepare_confirmation_document": (
        "catering_system.ui.office_panel.OfficePanel.prepare_confirmation_document"
    ),
    "mark_offer_sent": "catering_system.ui.office_panel.OfficePanel.mark_offer_sent",
    "record_offer_acceptance": (
        "catering_system.ui.office_panel.OfficePanel.record_offer_acceptance"
    ),
}


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
    ui_version: str = "v2",
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
        ui_version=ui_version,
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


def _legacy_panel_with_order() -> tuple[OfficePanel, str]:
    inquiry_repo = InMemoryInquiryRepository()
    order_repo = InMemoryOrderRepository()
    panel = OfficePanel(inquiry_repo, order_repo, ui_version="legacy")
    inquiry = panel.inquiry_service.create_inquiry(
        event_date=date(2026, 10, 1),
        inquiry_source="manual",
        crm_stage="Neue Anfrage",
        customer_linkage={},
        time_window_text="mittags",
        location_text="Hamburg",
        guest_count_estimate=10,
        planning_mode=PLANNING_MODES[0],
        call_verification_required=False,
        call_verification_status="not_required",
        contact_email="kunde@example.com",
        contact_phone="+49301234567",
    )
    order, _version = seed_order(order_repo, inquiry, order_id=_ORDER_ID)
    return panel, order.order_id


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


def test_payment_reminder_permission_registered_once() -> None:
    assert PERMISSION_REGISTRY.count("orders.payment.reminder") == 1
    assert "orders.payment.reminder" in PERMISSION_SET
    assert (
        validate_permission_code("orders.payment.reminder") == "orders.payment.reminder"
    )
    assert PERMISSION_LABELS["orders.payment.reminder"] == (
        "Zahlungserinnerungen verwalten"
    )


def test_payment_reminder_role_ceilings_and_defaults() -> None:
    assert "orders.payment.reminder" in role_ceiling("ADMIN")
    assert "orders.payment.reminder" in role_ceiling("USER")
    assert "orders.payment.reminder" not in VIEW_PERMISSION_SET
    with pytest.raises(ValueError, match="permissions exceed VIEWER ceiling"):
        ensure_permissions_within_role("VIEWER", {"orders.payment.reminder"})
    assert "orders.payment.reminder" not in ROLE_DEFAULT_GRANTS["ADMIN"]
    assert "orders.payment.reminder" not in ROLE_DEFAULT_GRANTS["USER"]
    assert effective_permissions("USER", {"orders.payment.reminder"}) == frozenset(
        {"orders.payment.reminder"}
    )


@pytest.mark.parametrize(("action", "required", "patch_name"), _ORDER_POST_ACTIONS)
def test_order_operational_post_denied_without_required_permission(
    employee_panel: PanelHarness,
    super_jar: http.cookiejar.CookieJar,
    action: str,
    required: str,
    patch_name: str,
) -> None:
    jar = _employee_jar(
        employee_panel,
        super_jar,
        username=f"denied.{action}",
        permissions=frozenset({"orders.view"}),
    )
    _assert_post_forbidden(
        employee_panel,
        f"/order/{_ORDER_ID}/{action}",
        jar=jar,
        data={"_csrf_token": _csrf(jar)},
        patches={patch_name: _PATCH_TARGETS[patch_name]},
    )
    assert required != "orders.view"


@pytest.mark.parametrize(
    ("action", "granted", "denied", "patch_name"),
    [
        (
            "print-confirm",
            "orders.version.create",
            "orders.print.confirm",
            "confirm_kitchen_print",
        ),
        (
            "effective",
            "orders.print.confirm",
            "orders.effective.set",
            "make_order_version_effective",
        ),
        (
            "ready",
            "orders.effective.set",
            "orders.ready.release",
            "request_ready_to_send",
        ),
        ("cancel", "orders.ready.release", "orders.cancel", "cancel_order"),
        (
            "version",
            "orders.payment.reminder",
            "orders.version.create",
            "create_version",
        ),
        (
            "payment-reminder",
            "orders.cancel",
            "orders.payment.reminder",
            "save_payment_reminder",
        ),
    ],
)
def test_order_permission_separation(
    employee_panel: PanelHarness,
    super_jar: http.cookiejar.CookieJar,
    action: str,
    granted: str,
    denied: str,
    patch_name: str,
) -> None:
    jar = _employee_jar(
        employee_panel,
        super_jar,
        username=f"sep.{action}.{granted}",
        permissions=frozenset({granted, "orders.view"}),
    )
    _assert_post_forbidden(
        employee_panel,
        f"/order/{_ORDER_ID}/{action}",
        jar=jar,
        data={"_csrf_token": _csrf(jar)},
        patches={patch_name: _PATCH_TARGETS[patch_name]},
    )
    assert granted != denied


def test_payment_reminder_succeeds_with_exact_permission(
    employee_panel: PanelHarness,
    super_jar: http.cookiejar.CookieJar,
) -> None:
    jar = _employee_jar(
        employee_panel,
        super_jar,
        username="payment.ok",
        permissions=frozenset({"orders.payment.reminder", "orders.view"}),
    )
    with patch(_PATCH_TARGETS["save_payment_reminder"], autospec=True) as save_mock:
        status, _url, _body, _headers = _request(
            employee_panel.base,
            f"/order/{_ORDER_ID}/payment-reminder",
            method="POST",
            data={
                "_csrf_token": _csrf(jar),
                "payment_method": "VORKASSE",
            },
            jar=jar,
        )
    assert status == 303
    save_mock.assert_called_once()


def test_version_create_succeeds_with_exact_permission(
    employee_panel: PanelHarness,
    super_jar: http.cookiejar.CookieJar,
) -> None:
    jar = _employee_jar(
        employee_panel,
        super_jar,
        username="version.ok",
        permissions=frozenset({"orders.version.create", "orders.view"}),
    )
    with patch(_PATCH_TARGETS["create_version"], autospec=True) as create_mock:
        status, _url, _body, _headers = _request(
            employee_panel.base,
            f"/order/{_ORDER_ID}/version",
            method="POST",
            data={
                "_csrf_token": _csrf(jar),
                "latest_version_number": "1",
                "event_date": "2026-10-01",
                "change_reason": "Kundenwunsch",
            },
            jar=jar,
        )
    assert status == 303
    create_mock.assert_called_once()


def test_authorized_order_post_still_requires_csrf(
    employee_panel: PanelHarness,
    super_jar: http.cookiejar.CookieJar,
) -> None:
    jar = _employee_jar(
        employee_panel,
        super_jar,
        username="ready.no.csrf",
        permissions=frozenset({"orders.ready.release"}),
    )
    with patch(_PATCH_TARGETS["request_ready_to_send"], autospec=True) as ready_mock:
        status, _url, body, _headers = _request(
            employee_panel.base,
            f"/order/{_ORDER_ID}/ready",
            method="POST",
            data={},
            jar=jar,
        )
    assert status == 403
    assert _GERMAN_CSRF in body
    assert _GERMAN_FORBIDDEN not in body
    ready_mock.assert_not_called()


def test_valid_csrf_still_yields_permission_denied_for_order_post(
    employee_panel: PanelHarness,
    super_jar: http.cookiejar.CookieJar,
) -> None:
    jar = _employee_jar(
        employee_panel,
        super_jar,
        username="viewer.with.csrf",
        permissions=frozenset({"orders.view"}),
    )
    with patch(_PATCH_TARGETS["cancel_order"], autospec=True) as cancel_mock:
        status, _url, body, _headers = _request(
            employee_panel.base,
            f"/order/{_ORDER_ID}/cancel",
            method="POST",
            data={"_csrf_token": _csrf(jar)},
            jar=jar,
        )
    assert status == 403
    assert _GERMAN_FORBIDDEN in body
    assert _GERMAN_CSRF not in body
    cancel_mock.assert_not_called()


def test_cross_session_csrf_returns_403_for_order_post(
    employee_panel: PanelHarness,
    super_jar: http.cookiejar.CookieJar,
) -> None:
    jar_a = super_jar
    jar_b = _employee_jar(
        employee_panel,
        super_jar,
        username="other.session",
        permissions=frozenset({"orders.cancel"}),
    )
    with patch(_PATCH_TARGETS["cancel_order"], autospec=True) as cancel_mock:
        status, _url, body, _headers = _request(
            employee_panel.base,
            f"/order/{_ORDER_ID}/cancel",
            method="POST",
            data={"_csrf_token": _csrf(jar_a)},
            jar=jar_b,
        )
    assert status == 403
    assert _GERMAN_CSRF in body
    cancel_mock.assert_not_called()


def test_migration_basic_fallback_retains_order_post(
    migration_panel: PanelHarness,
) -> None:
    with patch(_PATCH_TARGETS["request_ready_to_send"], autospec=True) as ready_mock:
        status, _url, _body, _headers = _request(
            migration_panel.base,
            f"/order/{_ORDER_ID}/ready",
            method="POST",
            data={"_csrf_token": csrf_token_for_password(migration_panel.password)},
            headers={"Authorization": _auth_header(migration_panel.password)},
        )
    assert status == 303
    ready_mock.assert_called_once()


def test_migration_employee_without_permission_denied(
    migration_panel: PanelHarness,
) -> None:
    super_jar = _ready_superadmin(migration_panel)
    jar = _employee_jar(
        migration_panel,
        super_jar,
        username="migration.viewer",
        permissions=frozenset({"orders.view"}),
    )
    _assert_post_forbidden(
        migration_panel,
        f"/order/{_ORDER_ID}/pause",
        jar=jar,
        data={"_csrf_token": _csrf(jar)},
        patches={"pause_order": _PATCH_TARGETS["pause_order"]},
    )


def test_migration_employee_session_takes_precedence_over_basic(
    migration_panel: PanelHarness,
) -> None:
    super_jar = _ready_superadmin(migration_panel)
    jar = _employee_jar(
        migration_panel,
        super_jar,
        username="migration.basic.precedence",
        permissions=frozenset({"orders.view"}),
    )
    _assert_post_forbidden(
        migration_panel,
        f"/order/{_ORDER_ID}/ready",
        jar=jar,
        data={"_csrf_token": _csrf(jar)},
        headers={"Authorization": _auth_header(migration_panel.password)},
        patches={"request_ready_to_send": _PATCH_TARGETS["request_ready_to_send"]},
    )


def test_unknown_order_action_returns_404_without_mutation(
    employee_panel: PanelHarness,
    super_jar: http.cookiejar.CookieJar,
) -> None:
    jar = super_jar
    with patch(_PATCH_TARGETS["create_version"], autospec=True) as create_mock:
        status, _url, _body, _headers = _request(
            employee_panel.base,
            f"/order/{_ORDER_ID}/not-a-real-action",
            method="POST",
            data={"_csrf_token": _csrf(jar)},
            jar=jar,
        )
    assert status == 404
    create_mock.assert_not_called()


def test_confirmation_document_routes_remain_auth2d3_protected(
    employee_panel: PanelHarness,
    super_jar: http.cookiejar.CookieJar,
) -> None:
    jar = _employee_jar(
        employee_panel,
        super_jar,
        username="doc.viewer",
        permissions=frozenset({"documents.view", "orders.view"}),
    )
    _assert_post_forbidden(
        employee_panel,
        f"/order/{_ORDER_ID}/confirmation-document",
        jar=jar,
        data={"_csrf_token": _csrf(jar)},
        patches={
            "prepare": _PATCH_TARGETS["prepare_confirmation_document"],
        },
    )
    _assert_post_forbidden(
        employee_panel,
        f"/order/{_ORDER_ID}/confirmation-document/send",
        jar=jar,
        data={
            "_csrf_token": _csrf(jar),
            "document_snapshot_id": "77777777-7777-4777-8777-777777777771",
        },
        patches={
            "send": "catering_system.ui.office_panel.OfficePanel.send_confirmation_test"
        },
    )


def test_auth2d1_get_routes_unchanged(
    employee_panel: PanelHarness,
    super_jar: http.cookiejar.CookieJar,
) -> None:
    jar = _employee_jar(
        employee_panel,
        super_jar,
        username="orders.reader",
        permissions=frozenset({"orders.view"}),
    )
    status, _url, body, _headers = _request(employee_panel.base, "/auftraege", jar=jar)
    assert status == 200
    assert "Aufträge" in body


def test_auth2d2_inquiry_convert_still_requires_composite_permission(
    employee_panel: PanelHarness,
    super_jar: http.cookiejar.CookieJar,
) -> None:
    jar = _employee_jar(
        employee_panel,
        super_jar,
        username="convert.view.only",
        permissions=frozenset({"inquiries.view"}),
    )
    _assert_post_forbidden(
        employee_panel,
        f"/inquiry/{_INQUIRY_ID}/convert",
        jar=jar,
        data={"_csrf_token": _csrf(jar)},
        patches={
            "convert": (
                "catering_system.ui.office_panel.OfficePanel.convert_inquiry_to_order"
            )
        },
    )


def test_domain_guard_still_rejects_authorized_invalid_payload(
    employee_panel: PanelHarness,
    super_jar: http.cookiejar.CookieJar,
) -> None:
    jar = _employee_jar(
        employee_panel,
        super_jar,
        username="print.invalid",
        permissions=frozenset({"orders.print.confirm", "orders.view"}),
    )
    with patch(_PATCH_TARGETS["confirm_kitchen_print"], autospec=True) as confirm_mock:
        status, _url, body, _headers = _request(
            employee_panel.base,
            f"/order/{_ORDER_ID}/print-confirm",
            method="POST",
            data={"_csrf_token": _csrf(jar)},
            jar=jar,
        )
    assert status == 400
    assert _GERMAN_FORBIDDEN not in body
    confirm_mock.assert_not_called()


def test_viewer_cannot_receive_order_mutation_permissions() -> None:
    for code in (
        "orders.version.create",
        "orders.print.confirm",
        "orders.effective.set",
        "orders.ready.release",
        "orders.pause",
        "orders.cancel",
        "orders.payment.reminder",
    ):
        with pytest.raises(ValueError, match="permissions exceed VIEWER ceiling"):
            ensure_permissions_within_role("VIEWER", {code})


def test_legacy_payment_reminder_hidden_without_permission() -> None:
    panel, order_id = _legacy_panel_with_order()
    page = panel.render_order(
        order_id,
        context=_employee_context("orders.view"),
    )
    assert page is not None
    assert "/payment-reminder" not in page
    assert "Zahlungshinweis speichern" not in page


def test_legacy_payment_reminder_shown_with_permission() -> None:
    panel, order_id = _legacy_panel_with_order()
    page = panel.render_order(
        order_id,
        context=_employee_context("orders.view", "orders.payment.reminder"),
    )
    assert page is not None
    assert "/payment-reminder" in page
    assert "Zahlungshinweis speichern" in page


def test_legacy_basic_fallback_retains_payment_reminder() -> None:
    panel, order_id = _legacy_panel_with_order()
    page = panel.render_order(order_id, context=legacy_office_context())
    assert page is not None
    assert "/payment-reminder" in page


def _v2_panel_with_order() -> tuple[OfficePanel, str]:
    inquiry_repo = InMemoryInquiryRepository()
    order_repo = InMemoryOrderRepository()
    panel = OfficePanel(inquiry_repo, order_repo, ui_version="v2")
    inquiry = panel.inquiry_service.create_inquiry(
        event_date=date(2026, 10, 1),
        inquiry_source="manual",
        crm_stage="Neue Anfrage",
        customer_linkage={},
        time_window_text="mittags",
        location_text="Hamburg",
        guest_count_estimate=10,
        planning_mode=PLANNING_MODES[0],
        call_verification_required=False,
        call_verification_status="not_required",
        contact_email="kunde@example.com",
        contact_phone="+49301234567",
    )
    order, _version = seed_order(order_repo, inquiry, order_id=_ORDER_ID)
    return panel, order.order_id


def test_v2_payment_reminder_hidden_without_permission() -> None:
    panel, order_id = _v2_panel_with_order()
    page = panel.render_order(
        order_id,
        context=_employee_context("orders.view"),
    )
    assert page is not None
    assert "/payment-reminder" not in page
    assert "Zahlungshinweis speichern" not in page


def test_v2_version_form_hidden_without_permission() -> None:
    panel, order_id = _v2_panel_with_order()
    page = panel.render_order(
        order_id,
        context=_employee_context("orders.view"),
    )
    assert page is not None
    assert "/version" not in page
    assert "Stand anlegen" not in page
    assert "Version anlegen" not in page
