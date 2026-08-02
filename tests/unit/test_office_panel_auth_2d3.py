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
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from catering_system.domain.employee_auth import (
    PERMISSION_REGISTRY,
    PERMISSION_SET,
    VIEW_PERMISSION_SET,
    effective_permissions,
    ensure_permissions_within_role,
    role_ceiling,
    validate_permission_code,
)
from catering_system.domain.order import Order
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
from catering_system.ui.office_panel_offer_detail import (
    OfferDetailFormFields,
    render_offer_detail,
)
from catering_system.ui.office_panel_order_detail import (
    OrderDetailFormFields,
    render_confirmation_outbound_card,
)
from catering_system.ui.office_panel_settings_users import PERMISSION_LABELS
from catering_system.ui.office_panel_views import OfficePageContext, _csrf_input
from tests.helpers.office_panel_context import legacy_office_context

_GERMAN_FORBIDDEN = "Ihre Berechtigung reicht für diese Aktion nicht aus."
_GERMAN_CSRF = "Ungültiger oder fehlender CSRF-Sicherheitstoken."
_OFFER_ID = "11111111-1111-4111-8111-111111111111"
_ORDER_ID = "66666666-6666-6666-6666-666666666666"
_VARIANT_ID = "44444444-4444-4444-8444-444444444441"
_ACCEPTANCE_ID = "55555555-5555-5555-5555-555555555555"


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


def _offer_detail(commercial_state: str) -> dict[str, object]:
    detail: dict[str, object] = {
        "offer_id": _OFFER_ID,
        "inquiry_id": "22222222-2222-2222-2222-222222222222",
        "commercial_state": commercial_state,
        "offer_version_id": "33333333-3333-4333-8333-333333333331",
        "versions": [
            {
                "offer_version_id": "33333333-3333-4333-8333-333333333331",
                "version": 1,
                "state": commercial_state,
                "created_at": "2026-07-15T08:00:00+00:00",
                "event_date": "2026-08-01",
                "valid_until": "2026-07-31",
                "time_window_text": "18:00",
                "location_text": "Hamburg",
                "guest_count": 50,
                "planning_mode": "caterer_suggestion",
                "variants": [
                    {
                        "variant_id": _VARIANT_ID,
                        "name": "Variante A",
                        "positions": [],
                    }
                ],
            }
        ],
        "history": [],
    }
    if commercial_state == "Accepted":
        detail["acceptance_id"] = _ACCEPTANCE_ID
        detail["acceptance"] = {"accepted_variant_id": _VARIANT_ID}
    return detail


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


def test_document_mutation_permissions_registered() -> None:
    assert "documents.prepare" in PERMISSION_REGISTRY
    assert "documents.send" in PERMISSION_REGISTRY
    assert validate_permission_code("documents.prepare") == "documents.prepare"
    assert validate_permission_code("documents.send") == "documents.send"
    assert "documents.prepare" in PERMISSION_LABELS
    assert "documents.send" in PERMISSION_LABELS


def test_viewer_ceiling_excludes_document_mutations() -> None:
    assert "documents.prepare" not in VIEW_PERMISSION_SET
    assert "documents.send" not in VIEW_PERMISSION_SET
    with pytest.raises(ValueError, match="permissions exceed VIEWER ceiling"):
        ensure_permissions_within_role(
            "VIEWER", {"documents.prepare", "documents.send"}
        )


def test_admin_and_user_may_receive_document_mutations_explicitly() -> None:
    assert "documents.prepare" in role_ceiling("ADMIN")
    assert "documents.send" in role_ceiling("ADMIN")
    assert "documents.prepare" in role_ceiling("USER")
    assert "documents.send" in role_ceiling("USER")
    ensure_permissions_within_role("ADMIN", {"documents.prepare"})
    ensure_permissions_within_role("USER", {"documents.send"})
    assert effective_permissions(
        "USER", {"documents.prepare", "documents.send"}
    ) == frozenset({"documents.prepare", "documents.send"})


def test_superadmin_ceiling_includes_document_mutations() -> None:
    assert "documents.prepare" in PERMISSION_SET
    assert "documents.send" in PERMISSION_SET


@pytest.mark.parametrize(
    ("action", "patch_target"),
    [
        (
            "mark-sent",
            "catering_system.ui.office_panel.OfficePanel.mark_offer_sent",
        ),
        (
            "record-acceptance",
            "catering_system.ui.office_panel.OfficePanel.record_offer_acceptance",
        ),
        (
            "record-rejection",
            "catering_system.ui.office_panel.OfficePanel.record_offer_rejection",
        ),
        (
            "record-withdrawal",
            "catering_system.ui.office_panel.OfficePanel.record_offer_withdrawal",
        ),
    ],
)
def test_offer_status_post_denied_without_required_permission(
    employee_panel: PanelHarness,
    super_jar: http.cookiejar.CookieJar,
    action: str,
    patch_target: str,
) -> None:
    required = "offers.send" if action == "mark-sent" else "offers.status.change"
    jar = _employee_jar(
        employee_panel,
        super_jar,
        username=f"denied.{action}",
        permissions=frozenset({"offers.view"}),
    )
    _assert_post_forbidden(
        employee_panel,
        f"/offer/{_OFFER_ID}/{action}",
        jar=jar,
        data={"_csrf_token": _csrf(jar)},
        patches={action: patch_target},
    )
    assert required != "offers.view"


def test_mark_sent_allowed_with_offers_send(
    employee_panel: PanelHarness,
    super_jar: http.cookiejar.CookieJar,
) -> None:
    jar = _employee_jar(
        employee_panel,
        super_jar,
        username="sender.ok",
        permissions=frozenset({"offers.send", "offers.view"}),
    )
    with patch.object(OfficePanel, "mark_offer_sent", autospec=True) as mark_mock:
        status, _url, _body, _headers = _request(
            employee_panel.base,
            f"/offer/{_OFFER_ID}/mark-sent",
            method="POST",
            data={
                "_csrf_token": _csrf(jar),
                "sent_at": "2026-09-01T10:00",
                "channel": "email",
                "recipient_reference": "kunde@example.test",
                "evidence_reference": "mail-1",
            },
            jar=jar,
        )
    assert status == 303
    mark_mock.assert_called_once()


@pytest.mark.parametrize(
    ("permissions", "username"),
    [
        (frozenset({"inquiries.view"}), "convert.neither"),
        (frozenset({"offers.view"}), "convert.view.only"),
        (frozenset({"orders.version.create"}), "convert.create.only"),
    ],
)
def test_offer_convert_requires_both_permissions(
    employee_panel: PanelHarness,
    super_jar: http.cookiejar.CookieJar,
    permissions: frozenset[str],
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
        f"/offer/{_OFFER_ID}/convert",
        jar=jar,
        data={
            "_csrf_token": _csrf(jar),
            "accepted_variant_id": _VARIANT_ID,
            "acceptance_id": _ACCEPTANCE_ID,
        },
        patches={
            "convert": "catering_system.ui.office_panel.OfficePanel.convert_accepted_offer"
        },
    )


def test_offer_convert_allowed_with_both_permissions(
    employee_panel: PanelHarness,
    super_jar: http.cookiejar.CookieJar,
) -> None:
    jar = _employee_jar(
        employee_panel,
        super_jar,
        username="convert.ok",
        permissions=frozenset({"offers.view", "orders.version.create"}),
    )
    fake_order = Order(
        order_id=_ORDER_ID,
        source_inquiry_id="22222222-2222-2222-2222-222222222222",
        created_at=datetime(2026, 8, 1, 10, 0, tzinfo=UTC),
        updated_at=datetime(2026, 8, 1, 10, 0, tzinfo=UTC),
    )
    with patch.object(
        OfficePanel, "convert_accepted_offer", autospec=True
    ) as convert_mock:
        convert_mock.return_value = (fake_order, object())
        status, _url, _body, _headers = _request(
            employee_panel.base,
            f"/offer/{_OFFER_ID}/convert",
            method="POST",
            data={
                "_csrf_token": _csrf(jar),
                "accepted_variant_id": _VARIANT_ID,
                "acceptance_id": _ACCEPTANCE_ID,
            },
            jar=jar,
        )
    assert status == 303
    convert_mock.assert_called_once()


def test_confirmation_prepare_denied_without_documents_prepare(
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
            "prepare": (
                "catering_system.ui.office_panel.OfficePanel.prepare_confirmation_document"
            )
        },
    )


def test_confirmation_send_denied_without_documents_send(
    employee_panel: PanelHarness,
    super_jar: http.cookiejar.CookieJar,
) -> None:
    jar = _employee_jar(
        employee_panel,
        super_jar,
        username="doc.preparer",
        permissions=frozenset({"documents.prepare", "documents.view", "orders.view"}),
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


def test_csrf_required_for_authorized_offer_post(
    employee_panel: PanelHarness,
    super_jar: http.cookiejar.CookieJar,
) -> None:
    jar = _employee_jar(
        employee_panel,
        super_jar,
        username="sender.no.csrf",
        permissions=frozenset({"offers.send"}),
    )
    with patch.object(OfficePanel, "mark_offer_sent", autospec=True) as mark_mock:
        status, _url, body, _headers = _request(
            employee_panel.base,
            f"/offer/{_OFFER_ID}/mark-sent",
            method="POST",
            data={
                "sent_at": "2026-09-01T10:00",
                "channel": "email",
                "recipient_reference": "kunde@example.test",
                "evidence_reference": "mail-1",
            },
            jar=jar,
        )
    assert status == 403
    assert _GERMAN_CSRF in body
    assert _GERMAN_FORBIDDEN not in body
    mark_mock.assert_not_called()


def test_valid_csrf_still_yields_permission_denied_for_offer_post(
    employee_panel: PanelHarness,
    super_jar: http.cookiejar.CookieJar,
) -> None:
    jar = _employee_jar(
        employee_panel,
        super_jar,
        username="viewer.with.csrf",
        permissions=frozenset({"offers.view"}),
    )
    with patch.object(OfficePanel, "mark_offer_sent", autospec=True) as mark_mock:
        status, _url, body, _headers = _request(
            employee_panel.base,
            f"/offer/{_OFFER_ID}/mark-sent",
            method="POST",
            data={"_csrf_token": _csrf(jar)},
            jar=jar,
        )
    assert status == 403
    assert _GERMAN_FORBIDDEN in body
    assert _GERMAN_CSRF not in body
    mark_mock.assert_not_called()


def test_migration_basic_fallback_retains_offer_post(
    migration_panel: PanelHarness,
) -> None:
    with patch.object(OfficePanel, "mark_offer_sent", autospec=True) as mark_mock:
        status, _url, _body, _headers = _request(
            migration_panel.base,
            f"/offer/{_OFFER_ID}/mark-sent",
            method="POST",
            data={
                "_csrf_token": csrf_token_for_password(migration_panel.password),
                "sent_at": "2026-09-01T10:00",
                "channel": "email",
                "recipient_reference": "kunde@example.test",
                "evidence_reference": "mail-1",
            },
            headers={"Authorization": _auth_header(migration_panel.password)},
        )
    assert status == 303
    mark_mock.assert_called_once()


def test_migration_employee_without_offers_send_gets_403(
    migration_panel: PanelHarness,
) -> None:
    super_jar = _ready_superadmin(migration_panel)
    jar = _employee_jar(
        migration_panel,
        super_jar,
        username="migration.viewer",
        permissions=frozenset({"offers.view"}),
    )
    _assert_post_forbidden(
        migration_panel,
        f"/offer/{_OFFER_ID}/mark-sent",
        jar=jar,
        data={"_csrf_token": _csrf(jar)},
        patches={
            "mark_offer_sent": (
                "catering_system.ui.office_panel.OfficePanel.mark_offer_sent"
            )
        },
    )


def test_offer_mark_sent_hidden_without_offers_send() -> None:
    forms = OfferDetailFormFields(
        csrf_input=_csrf_input(_employee_context()), command_fields=""
    )
    page = render_offer_detail(
        _offer_detail("Prepared"),
        context=_employee_context("offers.view"),
        forms=forms,
    )
    assert "Als gesendet markieren" not in page
    assert "/mark-sent" not in page

    allowed = render_offer_detail(
        _offer_detail("Prepared"),
        context=_employee_context("offers.view", "offers.send"),
        forms=forms,
    )
    assert "Als gesendet markieren" in allowed
    assert "/mark-sent" in allowed


def test_offer_status_actions_hidden_without_offers_status_change() -> None:
    forms = OfferDetailFormFields(
        csrf_input=_csrf_input(_employee_context()), command_fields=""
    )
    page = render_offer_detail(
        _offer_detail("Sent"),
        context=_employee_context("offers.view"),
        forms=forms,
    )
    assert "/record-acceptance" not in page
    assert "/record-rejection" not in page
    assert "/record-withdrawal" not in page

    allowed = render_offer_detail(
        _offer_detail("Sent"),
        context=_employee_context("offers.view", "offers.status.change"),
        forms=forms,
    )
    assert "/record-acceptance" in allowed
    assert "/record-rejection" in allowed
    assert "/record-withdrawal" in allowed


def test_offer_convert_hidden_without_composite_permissions() -> None:
    forms = OfferDetailFormFields(
        csrf_input=_csrf_input(_employee_context()), command_fields=""
    )
    page = render_offer_detail(
        _offer_detail("Accepted"),
        context=_employee_context("offers.view"),
        forms=forms,
    )
    assert "/convert" not in page
    assert "In Auftrag umwandeln" not in page

    page_create = render_offer_detail(
        _offer_detail("Accepted"),
        context=_employee_context("orders.version.create"),
        forms=forms,
    )
    assert "/convert" not in page_create

    allowed = render_offer_detail(
        _offer_detail("Accepted"),
        context=_employee_context("offers.view", "orders.version.create"),
        forms=forms,
    )
    assert "/convert" in allowed
    assert "In Auftrag umwandeln" in allowed


def test_legacy_office_context_retains_offer_actions() -> None:
    forms = OfferDetailFormFields(
        csrf_input=_csrf_input(legacy_office_context(csrf_token="csrf")),
        command_fields="",
    )
    page = render_offer_detail(
        _offer_detail("Prepared"),
        context=legacy_office_context(csrf_token="csrf"),
        forms=forms,
    )
    assert "Als gesendet markieren" in page


def test_confirmation_send_hidden_without_documents_send() -> None:
    from catering_system.services.order_confirmation_document_service import (
        OrderConfirmationDocumentEligibility,
        OrderConfirmationDocumentSummary,
    )
    from catering_system.services.order_confirmation_outbound_service import (
        OutboundSendEligibility,
    )

    now = datetime(2026, 8, 1, 10, 0, tzinfo=UTC)
    order = Order(
        order_id=_ORDER_ID,
        source_inquiry_id="22222222-2222-2222-2222-222222222222",
        created_at=now,
        updated_at=now,
    )
    snapshot = OrderConfirmationDocumentSummary(
        document_snapshot_id="77777777-7777-4777-8777-777777777771",
        order_id=_ORDER_ID,
        order_version_id="33333333-3333-4333-8333-333333333331",
        document_reference="AB-2026-0001",
        created_at=now,
        created_by="office-panel",
        recipient_status="ready",
        recipient_email_masked="k***@example.test",
        document_hash_short="abc123",
        net_total_cents=10000,
        vat_total_cents=700,
        gross_total_cents=10700,
        effective_version_number=1,
    )
    confirmation = OrderConfirmationDocumentEligibility(
        available=True,
        state="created",
        snapshot=snapshot,
    )
    outbound = OutboundSendEligibility(
        state="testversand_bereit",
        can_send=True,
    )
    forms = OrderDetailFormFields(
        csrf_input="",
        print_confirm_command_fields="",
        effective_command_fields="",
        ready_command_fields="",
        cancel_command_fields="",
        version_command_fields="",
        payment_command_fields="",
        send_command_fields="",
    )
    hidden = render_confirmation_outbound_card(
        order,
        confirmation,
        outbound,
        forms,
        context=_employee_context("documents.view", "documents.prepare"),
    )
    assert "/confirmation-document/send" not in hidden
    assert "Testversand erzeugen" not in hidden

    allowed = render_confirmation_outbound_card(
        order,
        confirmation,
        outbound,
        forms,
        context=_employee_context("documents.send"),
    )
    assert "/confirmation-document/send" in allowed
    assert "Testversand erzeugen" in allowed


def test_offers_send_alone_cannot_status_change(
    employee_panel: PanelHarness,
    super_jar: http.cookiejar.CookieJar,
) -> None:
    jar = _employee_jar(
        employee_panel,
        super_jar,
        username="sender.not.status",
        permissions=frozenset({"offers.send", "offers.view"}),
    )
    _assert_post_forbidden(
        employee_panel,
        f"/offer/{_OFFER_ID}/record-acceptance",
        jar=jar,
        data={
            "_csrf_token": _csrf(jar),
            "accepted_variant_id": _VARIANT_ID,
            "acceptance_id": _ACCEPTANCE_ID,
        },
        patches={
            "record_acceptance": (
                "catering_system.ui.office_panel.OfficePanel.record_offer_acceptance"
            )
        },
    )


def test_offers_status_change_alone_cannot_mark_sent(
    employee_panel: PanelHarness,
    super_jar: http.cookiejar.CookieJar,
) -> None:
    jar = _employee_jar(
        employee_panel,
        super_jar,
        username="status.not.sender",
        permissions=frozenset({"offers.status.change", "offers.view"}),
    )
    _assert_post_forbidden(
        employee_panel,
        f"/offer/{_OFFER_ID}/mark-sent",
        jar=jar,
        data={
            "_csrf_token": _csrf(jar),
            "sent_at": "2026-09-01T10:00",
            "channel": "email",
            "recipient_reference": "kunde@example.test",
            "evidence_reference": "mail-1",
        },
        patches={
            "mark_sent": "catering_system.ui.office_panel.OfficePanel.mark_offer_sent"
        },
    )


def test_confirmation_prepare_button_hidden_without_documents_prepare() -> None:
    from unittest.mock import MagicMock

    from catering_system.domain.order import Order
    from catering_system.services.order_confirmation_document_service import (
        OrderConfirmationDocumentEligibility,
    )
    from catering_system.ui.office_panel_order_detail import (
        ConfirmationLivePreviewView,
        OrderDetailFormFields,
        _confirmation_card,
    )

    now = datetime(2026, 8, 1, 10, 0, tzinfo=UTC)
    order = Order(
        order_id=_ORDER_ID,
        source_inquiry_id="22222222-2222-2222-2222-222222222222",
        created_at=now,
        updated_at=now,
    )
    preview = MagicMock()
    preview.eligible = True
    preview.blockers = ()
    preview.warnings = ()
    preview.commercial_reference = None
    live_preview = ConfirmationLivePreviewView(state="ready", preview=preview)
    forms = OrderDetailFormFields(
        csrf_input=_csrf_input(_employee_context()),
        print_confirm_command_fields={},
        effective_command_fields={},
        ready_command_fields="",
        cancel_command_fields="",
        version_command_fields="",
        payment_command_fields="",
        confirmation_command_fields="confirmed",
        send_command_fields="",
    )
    hidden = _confirmation_card(
        order,
        OrderConfirmationDocumentEligibility(
            available=True,
            state="ready",
            snapshot=None,
        ),
        forms,
        live_preview,
        context=_employee_context("orders.view", "documents.view"),
    )
    assert "/confirmation-document" not in hidden
    assert "Auftragsbestätigung erstellen" not in hidden

    allowed = _confirmation_card(
        order,
        OrderConfirmationDocumentEligibility(
            available=True,
            state="ready",
            snapshot=None,
        ),
        forms,
        live_preview,
        context=_employee_context("documents.prepare"),
    )
    assert "/confirmation-document" in allowed
    assert "Auftragsbestätigung erstellen" in allowed
