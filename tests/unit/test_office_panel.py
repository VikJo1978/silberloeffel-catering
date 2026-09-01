"""Unit tests — office panel (OFFICE_PANEL_EXECUTION_PACK_V1 §8). Live-socket, basic auth."""

from __future__ import annotations

import base64
import html
import json
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import UTC, date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from catering_system.domain.kitchen_print_job import KitchenPrintJob
from catering_system.domain.customer_document_preview import CustomerDocumentPreview
from catering_system.domain.customer_document_projection import (
    CustomerAddress,
    CustomerDocumentRecipient,
)
from catering_system.domain.order import Order, OrderVersion
from catering_system.domain.order_operational_context import (
    OrderVersionOperationalContextSnapshot,
)
from catering_system.domain.order_payment_reminder import derive_payment_reminder
from catering_system.domain.ready_to_send import ReadyToSendEvaluation
from catering_system.intake.website_form_adapter import intake_from_website_form
from catering_system.repositories.in_memory_inquiry_repository import (
    InMemoryInquiryRepository,
)
from catering_system.repositories.in_memory_kitchen_print_job_repository import (
    InMemoryKitchenPrintJobRepository,
)
from catering_system.repositories.in_memory_order_commercial_snapshot_repository import (
    InMemoryOrderCommercialSnapshotRepository,
)
from catering_system.repositories.in_memory_order_repository import (
    InMemoryOrderRepository,
)
from catering_system.services.inquiry_service import InquiryService
from catering_system.services.order_confirmation_document_service import (
    OrderConfirmationDocumentEligibility,
)
from catering_system.services.order_confirmation_outbound_service import (
    OutboundSendEligibility,
)
from catering_system.ui import office_api_views
from catering_system.ui.office_panel import (
    OfficePanel,
    create_office_panel_server,
)
from catering_system.ui.office_panel_http import (
    csrf_token_for_password,
    office_command_error_message,
)
from catering_system.ui.office_panel_order_detail import (
    ConfirmationLivePreviewView,
    OrderDetailFormFields,
    render_order_detail,
)
from catering_system.ui.office_panel_shell import OFFICE_PANEL_STYLE
from catering_system.ui.office_panel_tasks_list import SUBJECT_PICKER_SCRIPT_CSP_SOURCE
from catering_system.ui.office_panel_views import OfficePageContext, _page
from tests.helpers.commercial_snapshot_seed import seed_commercial_snapshot
from tests.helpers.office_panel_context import legacy_office_context
from tests.helpers.order_seed import seed_order


def test_delivery_context_conversion_error_is_actionable() -> None:
    message = office_command_error_message("delivery_context_unresolved")
    assert "Lieferdaten sind unvollständig" in message
    assert "Land" in message


_PASSWORD = "test-pw"
_AUTH = "Basic " + base64.b64encode(f"office:{_PASSWORD}".encode()).decode()
_CSRF_TOKEN = csrf_token_for_password(_PASSWORD)
_PANEL_REPOS: dict[
    str,
    tuple[
        InMemoryInquiryRepository,
        InMemoryOrderRepository,
        InMemoryOrderCommercialSnapshotRepository,
    ],
] = {}
_PANEL_JOBS: dict[str, InMemoryKitchenPrintJobRepository] = {}


@pytest.fixture()
def panel():
    inquiry_repo = InMemoryInquiryRepository()
    order_repo = InMemoryOrderRepository()
    snapshots = InMemoryOrderCommercialSnapshotRepository()
    kitchen_jobs = InMemoryKitchenPrintJobRepository(order_repo)
    server = create_office_panel_server(
        inquiry_repo,
        order_repo,
        _PASSWORD,
        host="127.0.0.1",
        port=0,
        commercial_snapshot_repo=snapshots,
        kitchen_print_job_repo=kitchen_jobs,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    base = f"http://{host}:{port}"
    _PANEL_REPOS[base] = (inquiry_repo, order_repo, snapshots)
    _PANEL_JOBS[base] = kitchen_jobs
    yield base
    _PANEL_REPOS.pop(base, None)
    _PANEL_JOBS.pop(base, None)
    server.shutdown()
    server.server_close()


@pytest.fixture()
def premium_panel():
    inquiry_repo = InMemoryInquiryRepository()
    order_repo = InMemoryOrderRepository()
    snapshots = InMemoryOrderCommercialSnapshotRepository()
    kitchen_jobs = InMemoryKitchenPrintJobRepository(order_repo)
    server = create_office_panel_server(
        inquiry_repo,
        order_repo,
        _PASSWORD,
        host="127.0.0.1",
        port=0,
        commercial_snapshot_repo=snapshots,
        kitchen_print_job_repo=kitchen_jobs,
        ui_version="v2",
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    base = f"http://{host}:{port}"
    _PANEL_REPOS[base] = (inquiry_repo, order_repo, snapshots)
    _PANEL_JOBS[base] = kitchen_jobs
    yield base
    _PANEL_REPOS.pop(base, None)
    _PANEL_JOBS.pop(base, None)
    server.shutdown()
    server.server_close()


def _get(url: str, *, auth: bool = True) -> tuple[int, str]:
    req = urllib.request.Request(url)
    if auth:
        req.add_header("Authorization", _AUTH)
    with urllib.request.urlopen(req) as resp:
        return resp.status, resp.read().decode("utf-8")


def _post(
    url: str,
    data: dict[str, str],
    *,
    auth: bool = True,
    csrf: bool = True,
) -> tuple[int, str, str]:
    """Returns (status, final_url, body); urllib follows the 303 into a GET."""
    payload = dict(data)
    if csrf:
        payload.setdefault("_csrf_token", _CSRF_TOKEN)
    req = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(payload).encode(),
        method="POST",
    )
    if auth:
        req.add_header("Authorization", _AUTH)
    with urllib.request.urlopen(req) as resp:
        return resp.status, resp.url, resp.read().decode("utf-8")


def _create_inquiry(base: str, **overrides: str) -> str:
    data = {
        "event_date": "2026-10-01",
        "time_window_text": "mittags",
        "location_text": "Hamburg",
        "guest_count_estimate": "25",
        "planning_mode": "caterer_suggestion",
        "contact_email": "kunde@example.com",
        "contact_phone": "030 1234567",
    }
    data.update(overrides)
    _status, url, _body = _post(f"{base}/inquiry/new", data)
    return url.rsplit("/", 1)[-1]  # inquiry id from redirect target


def _create_website_form_inquiry(base: str) -> str:
    inquiries, orders, _snapshots = _PANEL_REPOS[base]
    office = OfficePanel(inquiries, orders)
    inquiry = intake_from_website_form(
        office.inquiry_service,
        {
            "event_date": date(2026, 10, 1),
            "location_text": "Hamburg",
            "guest_count_estimate": 25,
            "company": "Website Anfrage GmbH",
            "email": "kunde@example.com",
            "phone": "040 123456",
            "submission_id": "web-42",
        },
    )
    return inquiry.inquiry_id


def _convert(base: str, inquiry_id: str) -> str:
    """Seed an Order for panel tests (no production Inquiry→Order create)."""
    from dataclasses import replace

    inquiries, orders, snapshots = _PANEL_REPOS[base]
    inquiry = inquiries.get_by_id(inquiry_id)
    assert inquiry is not None
    order, _version = seed_order(orders, inquiry)
    seed_commercial_snapshot(snapshots, order.order_id)
    inquiries.update(
        replace(inquiry, crm_stage="Bestätigt / Auftrag")  # type: ignore[arg-type]
    )
    return order.order_id


def _set_fulfillment_mode(
    base: str,
    inquiry_id: str,
    fulfillment_mode: str,
) -> None:
    inquiries, _orders, _snapshots = _PANEL_REPOS[base]
    InquiryService(inquiries).set_inquiry_fulfillment_mode(
        inquiry_id,
        fulfillment_mode=fulfillment_mode,
    )


def _set_delivery_address(base: str, inquiry_id: str) -> None:
    inquiries, _orders, _snapshots = _PANEL_REPOS[base]
    address = CustomerAddress(
        street="Lieferweg 12",
        postal_code="20095",
        city="Hamburg",
        country="Deutschland",
    )
    InquiryService(inquiries).set_inquiry_customer_addresses(
        inquiry_id,
        invoice_address=address,
        delivery_address=address,
        delivery_address_mode="SEPARATE",
    )


def _next_step_section(body: str) -> str:
    return body.split('<section class="order-next-step', 1)[1].split("</section>", 1)[0]


def _status_card_section(body: str) -> str:
    return body.split(
        '<section class="order-card order-content-card order-status-card"', 1
    )[1].split("</section>", 1)[0]


def _simulate_kitchen_agent_ack(base: str, order_version_id: str) -> None:
    from catering_system.services.kitchen_print_service import KitchenPrintService

    _inquiries, orders, _snapshots = _PANEL_REPOS[base]
    service = KitchenPrintService(orders, _PANEL_JOBS[base])
    claimed = service.claim_next_eligible()
    assert claimed is not None
    assert claimed.order_version_id == order_version_id
    service.acknowledge_print_job(claimed.print_job_id)


def test_v2_shell_uses_explicit_active_section_and_semantic_landmarks() -> None:
    body = _page(
        "Anfragen",
        "<p>Inhalt</p>",
        active_section="orders",
        context=legacy_office_context(),
    )

    assert '<nav class="office-nav" aria-label="Office Panel">' in body
    assert '<main class="office-workspace">' in body
    assert '<a class="office-nav-link" href="/orders" aria-current="page">' in body
    assert (
        '<a class="office-nav-link" href="/anfragen" aria-current="page">' not in body
    )
    assert body.count("<h1>") == 1


def test_v2_shell_is_local_no_js_and_has_complete_inline_icon_sprite() -> None:
    body = _page(
        "Büro-Übersicht",
        "<p>Inhalt</p>",
        active_section="home",
        context=legacy_office_context(),
    )

    assert "<script" not in body
    assert "fonts.googleapis.com" not in body
    assert "fonts.gstatic.com" not in body
    assert "@import" not in body
    assert "/Users/viktorjohanson/office_panell" not in body
    assert '<meta name="viewport"' in body
    for target in (
        'href="/"',
        'href="/anfragen"',
        'href="/orders"',
        'href="/#diese-woche"',
        'href="/rueckruf"',
    ):
        assert target in body

    references = set(re.findall(r'<use href="#(office-i-[^"]+)"', body))
    symbols = set(re.findall(r'<symbol id="(office-i-[^"]+)"', body))
    # The shared sprite also carries dashboard-only icons, so a bare page
    # references a subset. The explicit inventory below still guards against
    # dead sprite entries — extend it only together with a page that uses
    # the new icon (see test_office_panel_dashboard.py).
    assert references <= symbols
    assert symbols == {
        "office-i-grid",
        "office-i-doc",
        "office-i-briefcase",
        "office-i-calendar",
        "office-i-phone",
        "office-i-users",
        "office-i-printer",
        "office-i-check",
        "office-i-chat",
    }
    assert all(body.count(f'<symbol id="{symbol}"') == 1 for symbol in symbols)


def test_page_context_badge_does_not_leak_between_renders() -> None:
    with_badge = _page(
        "Neue Anfrage",
        "<p>Inhalt</p>",
        active_section="inquiries",
        context=legacy_office_context(rueckruf_count=3),
    )
    without_badge = _page(
        "Neue Anfrage",
        "<p>Inhalt</p>",
        active_section="inquiries",
        context=legacy_office_context(),
    )

    assert '<span class="badge">3</span>' in with_badge
    assert '<span class="badge">' not in without_badge


def test_v2_mobile_navigation_is_visible_without_javascript() -> None:
    assert "@media (max-width: 820px)" in OFFICE_PANEL_STYLE
    mobile_css = OFFICE_PANEL_STYLE.split("@media (max-width: 820px)", 1)[1]
    assert ".office-sidebar {" in mobile_css
    assert "position: static;" in mobile_css
    assert ".office-nav {" in mobile_css
    assert "display: flex;" in mobile_css
    assert "overflow-x: auto;" in mobile_css
    assert "transform: translateX" not in mobile_css
    assert ".js " not in OFFICE_PANEL_STYLE


@pytest.mark.parametrize(
    ("path", "current_href"),
    (
        ("/", "/"),
        ("/anfragen", "/anfragen"),
        ("/orders", "/orders"),
        ("/inquiry/new", "/anfragen"),
        ("/rueckruf", "/rueckruf"),
    ),
)
def test_shell_marks_current_navigation_for_route_groups(
    panel: str, path: str, current_href: str
) -> None:
    status, body = _get(f"{panel}{path}")

    assert status == 200
    assert (
        len(re.findall(r'<a class="office-nav-link"[^>]*aria-current="page"', body))
        == 1
    )
    assert (
        f'<a class="office-nav-link" href="{current_href}" aria-current="page">' in body
    )


def test_detail_routes_mark_their_parent_navigation(panel: str) -> None:
    inquiry_id = _create_inquiry(panel)
    _status, inquiry_body = _get(f"{panel}/inquiry/{inquiry_id}")
    assert (
        '<a class="office-nav-link" href="/anfragen" aria-current="page">'
        in inquiry_body
    )

    order_id = _convert(panel, inquiry_id)
    _status, order_body = _get(f"{panel}/order/{order_id}")
    assert (
        '<a class="office-nav-link" href="/orders" aria-current="page">' in order_body
    )


# -- auth ---------------------------------------------------------------


def test_get_requires_auth(panel: str) -> None:
    with pytest.raises(urllib.error.HTTPError) as exc:
        _get(f"{panel}/", auth=False)
    assert exc.value.code == 401


def test_post_requires_auth(panel: str) -> None:
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(f"{panel}/inquiry/new", {"event_date": "2026-10-01"}, auth=False)
    assert exc.value.code == 401


def test_post_requires_valid_csrf_token(panel: str) -> None:
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(
            f"{panel}/inquiry/new",
            {"event_date": "2026-10-01", "location_text": "CSRF-NO-MUTATION"},
            csrf=False,
        )
    assert exc.value.code == 403

    _status, body = _get(f"{panel}/anfragen")
    assert "CSRF-NO-MUTATION" not in body


def test_post_rejects_wrong_csrf_token(panel: str) -> None:
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(
            f"{panel}/inquiry/new",
            {"event_date": "2026-10-01", "_csrf_token": "wrong"},
        )
    assert exc.value.code == 403


def _assert_all_post_forms_have_csrf(body: str) -> None:
    forms = re.findall(
        r'<form\b[^>]*method="post"[^>]*>.*?</form>', body, flags=re.DOTALL
    )
    assert forms
    expected = f'name="_csrf_token" value="{_CSRF_TOKEN}"'
    assert all(expected in form for form in forms)


def test_http_rendered_post_forms_include_csrf_token(panel: str) -> None:
    _status, new_inquiry_page = _get(f"{panel}/inquiry/new")
    _assert_all_post_forms_have_csrf(new_inquiry_page)

    inquiry_id = _create_inquiry(panel)
    _status, inquiry_page = _get(f"{panel}/inquiry/{inquiry_id}")
    _assert_all_post_forms_have_csrf(inquiry_page)

    order_id = _convert(panel, inquiry_id)
    _status, order_page = _get(f"{panel}/order/{order_id}")
    _assert_all_post_forms_have_csrf(order_page)


def test_office_panel_sets_security_headers(panel: str) -> None:
    request = urllib.request.Request(f"{panel}/")
    request.add_header("Authorization", _AUTH)
    with urllib.request.urlopen(request) as response:
        assert response.headers["Cache-Control"] == "no-store"
        csp = response.headers["Content-Security-Policy"]
        assert "form-action 'self'" in csp
        assert "frame-ancestors 'none'" in csp
        assert "fonts.googleapis.com" not in csp
        assert "fonts.gstatic.com" not in csp
        assert "font-src" not in csp
        assert f"script-src {SUBJECT_PICKER_SCRIPT_CSP_SOURCE};" in csp
        assert "script-src 'unsafe-inline'" not in csp
        assert response.headers["Referrer-Policy"] == "no-referrer"
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"


def test_office_panel_rejects_oversized_form_body(panel: str) -> None:
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(
            f"{panel}/inquiry/new",
            {
                "event_date": "2026-10-01",
                "guest_count_estimate": "25",
                "location_text": "Hamburg",
                "time_window_text": "mittags",
                "planning_mode": "caterer_suggestion",
                "intake_message": "x" * (300 * 1024),
            },
        )
    assert exc.value.code == 413


def test_wrong_password_rejected(panel: str) -> None:
    req = urllib.request.Request(f"{panel}/")
    req.add_header(
        "Authorization", "Basic " + base64.b64encode(b"office:wrong").decode()
    )
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req)
    assert exc.value.code == 401


# -- inquiries ----------------------------------------------------------


def test_queue_renders_empty(panel: str) -> None:
    status, body = _get(f"{panel}/")
    assert status == 200
    assert "Anfragen" in body and "Aufträge" in body


def test_create_inquiry_appears_in_queue(panel: str) -> None:
    iid = _create_inquiry(panel)
    _status, body = _get(f"{panel}/")
    assert iid[:8] in body
    assert "Hamburg" in body


def test_inquiry_timing_is_shown_once_with_exact_fields(premium_panel: str) -> None:
    iid = _create_inquiry(
        premium_panel,
        delivery_time_local="16:30",
        event_start_local="18:00",
    )
    _status, body = _get(f"{premium_panel}/inquiry/{iid}")

    assert "<dt>Lieferung</dt><dd>16:30</dd>" in body
    assert "<dt>Beginn Veranstaltung</dt><dd>18:00</dd>" in body
    assert 'name="delivery_time_local" value="16:30"' in body
    assert 'name="event_start_local" value="18:00"' in body
    assert 'name="time_window_text"' not in body
    assert "<dt>Zeit</dt>" not in body
    assert "Zeitfenster</label>" not in body


def test_inquiry_detail_and_update(panel: str) -> None:
    iid = _create_inquiry(panel)
    _status, _url, body = _post(
        f"{panel}/inquiry/{iid}/update",
        {
            "event_date": "2026-10-02",
            "time_window_text": "abends",
            "location_text": "Kiel",
            "guest_count_estimate": "",
            "planning_mode": "self_select",
            "crm_stage": "In Prüfung",
        },
    )
    assert "Kiel" in body and "2026-10-02" in body and "In Prüfung" in body


def test_unverified_inquiry_shows_progression_block_and_convert_fails(
    panel: str,
) -> None:
    iid = _create_inquiry(panel, call_verification_required="1")
    _status, body = _get(f"{panel}/inquiry/{iid}")
    assert "Konvertierung blockiert" in body
    assert (
        "Rückrufprüfung noch nicht erfüllt" in body
    )  # B7 vocabulary, human label, on inquiry view
    assert "Telefonisch verifiziert" in body
    assert "Auftrag erstellen" not in body
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(f"{panel}/inquiry/{iid}/convert", {})
    assert exc.value.code == 400


def test_verify_then_prepare_offer_path(panel: str) -> None:
    iid = _create_inquiry(panel, call_verification_required="1")
    _status, _url, body = _post(f"{panel}/inquiry/{iid}/verify", {})
    assert "verifiziert" in body
    _status, inquiry_body = _get(f"{panel}/inquiry/{iid}")
    assert (
        "Angebot vorbereiten" in inquiry_body
        or "Auftrag nur aus angenommenem Angebot" in inquiry_body
        or "Angebot kann vorbereitet werden" in inquiry_body
    )
    assert "Auftrag erstellen" not in inquiry_body
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(f"{panel}/inquiry/{iid}/convert", {})
    assert exc.value.code == 400


def test_order_payment_reminder_is_separate_and_truthful(panel: str) -> None:
    inquiry_id = _create_inquiry(panel)
    order_id = _convert(panel, inquiry_id)

    status, initial = _get(f"{panel}/order/{order_id}")
    assert status == 200
    assert "<h2>Zahlung</h2>" in initial
    assert "Zahlungsart:</strong> Noch nicht gewählt" in initial
    assert "Nächster Schritt:</strong> Zahlungsart auswählen" in initial
    assert f'action="/order/{order_id}/payment-reminder"' in initial
    assert "Küchendruck starten" in initial

    status, _url, saved = _post(
        f"{panel}/order/{order_id}/payment-reminder",
        {
            "payment_method": "VORKASSE",
            "invoice_created": "1",
            "invoice_number": "RE-2026-0048",
            "sent_on": "2026-07-15",
            "due_on": (office_api_views.berlin_today() + timedelta(days=7)).isoformat(),
        },
    )
    assert status == 200
    assert "Zahlungsart:</strong> Vorkasse" in saved
    assert "Rechnungsnummer:</strong> RE-2026-0048" in saved
    assert "Nächster Schritt:</strong> Zahlungseingang prüfen" in saved
    assert "Küchendruck starten" in saved


def test_cancelled_order_payment_reminder_is_read_only(panel: str) -> None:
    inquiry_id = _create_inquiry(panel)
    order_id = _convert(panel, inquiry_id)
    _post(f"{panel}/order/{order_id}/cancel", {})

    _status, body = _get(f"{panel}/order/{order_id}")

    assert "Zahlungsart:</strong> Noch nicht gewählt" in body
    assert f'action="/order/{order_id}/payment-reminder"' not in body


def test_converted_inquiry_shows_order_link_instead_of_button(panel: str) -> None:
    iid = _create_inquiry(panel)
    oid = _convert(panel, iid)
    _status, body = _get(f"{panel}/inquiry/{iid}")
    assert "Auftrag vorhanden" in body and oid[:8] in body
    assert "Auftrag erstellen" not in body
    assert '<select name="crm_stage">' not in body
    assert '<input type="hidden" name="crm_stage" value="Bestätigt / Auftrag">' in body


def test_active_order_rejects_incompatible_inquiry_stage_update(panel: str) -> None:
    iid = _create_inquiry(panel)
    oid = _convert(panel, iid)

    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(
            f"{panel}/inquiry/{iid}/update",
            {
                "event_date": "2026-10-01",
                "time_window_text": "mittags",
                "location_text": "Hamburg",
                "guest_count_estimate": "25",
                "planning_mode": "caterer_suggestion",
                "crm_stage": "Abgelehnt / verloren",
            },
        )
    assert exc.value.code == 400

    _status, body = _get(f"{panel}/inquiry/{iid}")
    assert "Bestätigt / Auftrag" in body
    assert "Auftrag vorhanden" in body and oid[:8] in body


def test_rejected_inquiry_is_closed_without_queue_or_actions(panel: str) -> None:
    iid = _create_inquiry(panel, call_verification_required="1")
    _post(
        f"{panel}/inquiry/{iid}/update",
        {
            "event_date": "2026-10-01",
            "time_window_text": "mittags",
            "location_text": "Hamburg",
            "guest_count_estimate": "25",
            "planning_mode": "caterer_suggestion",
            "crm_stage": "Abgelehnt / verloren",
        },
    )

    _status, detail = _get(f"{panel}/inquiry/{iid}")
    assert "Anfrage wurde abgelehnt" in detail
    assert "Telefonisch verifiziert" not in detail
    assert "Auftrag erstellen" not in detail
    _status, dashboard = _get(f"{panel}/")
    assert _attention_counts(dashboard)["Offene Anfragen prüfen"] == 0

    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(f"{panel}/inquiry/{iid}/convert", {})
    assert exc.value.code == 400


def test_v2_inquiry_detail_ready_to_convert_and_verification_required(
    premium_panel: str,
) -> None:
    ready_id = _create_inquiry(
        premium_panel,
        intake_subject="Sommerfest HafenCity",
        intake_message="Bitte um ein Angebot für unser Sommerfest.",
    )
    verify_id = _create_inquiry(
        premium_panel,
        call_verification_required="1",
        intake_subject="Firmenfeier",
    )

    _status, ready = _get(f"{premium_panel}/inquiry/{ready_id}")
    _status, verify = _get(f"{premium_panel}/inquiry/{verify_id}")

    assert "inquiry-hero" in ready
    assert "<h1>Sommerfest HafenCity</h1>" in ready
    assert "Angebot vorbereiten" in ready
    assert f'action="/inquiry/{ready_id}/convert"' not in ready
    assert "Auftrag erstellen" not in ready
    assert "Telefonisch verifiziert" not in ready
    assert "Rückruf erforderlich" in verify
    assert "Rückrufprüfung noch nicht erfüllt" in verify
    assert f'action="/inquiry/{verify_id}/verify"' in verify
    assert "Telefonisch verifiziert" in verify
    assert "Auftrag erstellen" not in verify


def test_v2_inquiry_detail_rejected_has_no_primary_action(
    premium_panel: str,
) -> None:
    inquiry_id = _create_inquiry(
        premium_panel,
        call_verification_required="1",
        intake_subject="Abgesagte Feier",
    )
    _post(
        f"{premium_panel}/inquiry/{inquiry_id}/update",
        {
            "event_date": "2026-10-01",
            "time_window_text": "mittags",
            "location_text": "Hamburg",
            "guest_count_estimate": "25",
            "planning_mode": "caterer_suggestion",
            "crm_stage": "Abgelehnt / verloren",
        },
    )

    _status, body = _get(f"{premium_panel}/inquiry/{inquiry_id}")

    assert "Anfrage abgeschlossen" in body
    assert "Anfrage wurde abgelehnt" in body
    assert f'action="/inquiry/{inquiry_id}/verify"' not in body
    assert f'action="/inquiry/{inquiry_id}/convert"' not in body


def test_v2_inquiry_detail_active_and_cancelled_order_history(
    premium_panel: str,
) -> None:
    active_inquiry_id = _create_inquiry(premium_panel, intake_subject="Business Lunch")
    active_order_id = _convert(premium_panel, active_inquiry_id)
    cancelled_inquiry_id = _create_inquiry(
        premium_panel, intake_subject="Sommerempfang"
    )
    cancelled_order_id = _convert(premium_panel, cancelled_inquiry_id)
    _post(f"{premium_panel}/order/{cancelled_order_id}/cancel", {})

    _status, active = _get(f"{premium_panel}/inquiry/{active_inquiry_id}")
    _status, cancelled = _get(f"{premium_panel}/inquiry/{cancelled_inquiry_id}")

    assert "Auftrag vorhanden" in active
    assert f'href="/order/{active_order_id}"' in active
    assert "Auftrag öffnen" in active
    assert f'action="/inquiry/{active_inquiry_id}/convert"' not in active
    assert '<select name="crm_stage">' not in active
    assert (
        '<input type="hidden" name="crm_stage" value="Bestätigt / Auftrag">' in active
    )
    assert f'href="/order/{cancelled_order_id}"' in cancelled
    assert "Auftrag öffnen" in cancelled
    assert f'action="/inquiry/{cancelled_inquiry_id}/convert"' not in cancelled

    visible_active = html.unescape(re.sub(r"<[^>]+>", " ", active))
    visible_cancelled = html.unescape(re.sub(r"<[^>]+>", " ", cancelled))
    assert active_order_id[:8] not in visible_active
    assert cancelled_order_id[:8] not in visible_cancelled


def test_v2_inquiry_detail_escapes_hostile_intake_and_hides_technical_values(
    premium_panel: str,
) -> None:
    inquiry_id = _create_inquiry(
        premium_panel,
        intake_subject='<img src=x onerror="alert(1)">',
        intake_message="<script>alert('message')</script>",
        intake_summary='<svg onload="alert(2)">Zusammenfassung</svg>',
        intake_external_ref="<b>EXT-7</b>",
    )

    _status, body = _get(f"{premium_panel}/inquiry/{inquiry_id}")
    visible = html.unescape(re.sub(r"<[^>]+>", " ", body))

    assert "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;" in body
    assert "&lt;script&gt;alert(&#x27;message&#x27;)&lt;/script&gt;" in body
    assert "&lt;svg onload=&quot;alert(2)&quot;&gt;" in body
    assert "&lt;b&gt;EXT-7&lt;/b&gt;" in body
    assert "<script>alert" not in body
    assert '<img src=x onerror="alert(1)">' not in body
    assert inquiry_id[:8] not in visible
    assert "caterer_suggestion" not in visible
    assert "inquiry_call_verification_unsatisfied" not in visible
    assert "Möbel & Mehr GmbH" not in body
    assert '<details class="inquiry-edit">' in body
    assert f'action="/inquiry/{inquiry_id}/update"' in body
    assert 'name="_csrf_token"' in body


def test_open_queue_shows_actual_crm_stage(panel: str) -> None:
    iid = _create_inquiry(panel)
    _post(
        f"{panel}/inquiry/{iid}/update",
        {
            "event_date": "2026-10-01",
            "time_window_text": "mittags",
            "location_text": "Hamburg",
            "guest_count_estimate": "25",
            "planning_mode": "caterer_suggestion",
            "crm_stage": "Angebot gesendet / Rückmeldung offen",
        },
    )

    _status, dashboard = _get(f"{panel}/")
    assert "Angebot gesendet / Rückmeldung offen" in dashboard
    assert "Angebot vorbereiten" in dashboard
    assert f'action="/inquiry/{iid}/convert"' not in dashboard


# -- intake context (INQUIRY_INTAKE_CONTEXT_FIELDS_IMPLEMENTATION_PACK_V1) --


def test_new_inquiry_form_hides_kanal_and_source_field(panel: str) -> None:
    status, body = _get(f"{panel}/inquiry/new")
    assert status == 200
    assert "Intake-Kontext — keine Auftrags-/Küchenfreigabe." in body
    assert "Kanal" not in body
    assert 'name="inquiry_source"' not in body


def test_inquiry_form_prefills_from_query(panel: str) -> None:
    status, body = _get(
        f"{panel}/inquiry/new?event_date=2026-09-12&guest_count_estimate=30"
    )
    assert status == 200
    assert 'name="event_date" value="2026-09-12"' in body
    assert 'name="guest_count_estimate" inputmode="numeric" value="30"' in body
    assert "Anfrage anlegen" in body


def test_inquiry_form_without_query_renders_empty_prefill(panel: str) -> None:
    status, body = _get(f"{panel}/inquiry/new")
    assert status == 200
    assert 'name="event_date" value=""' in body
    assert 'name="guest_count_estimate" inputmode="numeric" value=""' in body


def test_prepare_link_get_creates_nothing_in_core() -> None:
    """Following the inquiry/new GET (with query hints) must not create anything."""
    inquiry_repo = InMemoryInquiryRepository()
    order_repo = InMemoryOrderRepository()
    server = create_office_panel_server(
        inquiry_repo, order_repo, _PASSWORD, host="127.0.0.1", port=0
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        status, _body = _get(
            f"http://{host}:{port}/inquiry/new?event_date=2026-09-12&guest_count_estimate=30"
        )
        assert status == 200
        assert inquiry_repo.list_all() == []
        assert order_repo.list_orders() == []
    finally:
        server.shutdown()
        server.server_close()


def test_manual_submit_wins_over_query_hints() -> None:
    """Query hints are prefill only: submitted form values create the Inquiry."""
    inquiry_repo = InMemoryInquiryRepository()
    order_repo = InMemoryOrderRepository()
    server = create_office_panel_server(
        inquiry_repo, order_repo, _PASSWORD, host="127.0.0.1", port=0
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    base = f"http://{host}:{port}"
    try:
        _status, _url, _body = _post(
            f"{base}/inquiry/new",
            {
                "event_date": "2026-10-05",
                "time_window_text": "",
                "location_text": "",
                "guest_count_estimate": "25",
                "planning_mode": "caterer_suggestion",
                "contact_email": "kunde@example.com",
                "contact_phone": "030 1234567",
            },
        )
        inquiries = inquiry_repo.list_all()
        assert len(inquiries) == 1
        assert inquiries[0].event_date.isoformat() == "2026-10-05"
        assert inquiries[0].guest_count_estimate == 25
        assert inquiries[0].inquiry_source == "phone_by_office"
        assert order_repo.list_orders() == []
    finally:
        server.shutdown()
        server.server_close()


def test_post_new_inquiry_creates_phone_by_office_source(panel: str) -> None:
    inquiry_id = _create_inquiry(panel)
    inquiries, _orders, _snapshots = _PANEL_REPOS[panel]
    inquiry = inquiries.get_by_id(inquiry_id)
    assert inquiry is not None
    assert inquiry.inquiry_source == "phone_by_office"


def test_post_new_inquiry_ignores_tampered_source(panel: str) -> None:
    inquiry_id = _create_inquiry(panel, inquiry_source="email")
    inquiries, _orders, _snapshots = _PANEL_REPOS[panel]
    inquiry = inquiries.get_by_id(inquiry_id)
    assert inquiry is not None
    assert inquiry.inquiry_source == "phone_by_office"


def test_create_inquiry_without_intake_fields_still_works(panel: str) -> None:
    iid = _create_inquiry(panel)
    _status, body = _get(f"{panel}/inquiry/{iid}")
    assert "Vorgangsprüfung" in body
    # summary table stays free of intake rows when nothing was entered (the
    # edit form below always shows the four labeled inputs, empty — that's
    # expected, checked separately by the "stores and shows them" test)
    assert "<th>Betreff</th>" not in body
    assert "<th>Nachricht</th>" not in body
    assert "<th>Zusammenfassung</th>" not in body
    assert "<th>Externe Referenz</th>" not in body


def test_create_inquiry_with_intake_fields_stores_and_shows_them(panel: str) -> None:
    iid = _create_inquiry(
        panel,
        intake_subject="Firmenfeier Musterfirma",
        intake_message="Kunde möchte Buffet für 30 Personen, Rückruf gewünscht.",
        intake_summary="30 Pers., Buffet, Rückruf",
        intake_external_ref="proposal-42",
    )
    _status, body = _get(f"{panel}/inquiry/{iid}")
    assert "Firmenfeier Musterfirma" in body
    assert "Kunde möchte Buffet für 30 Personen, Rückruf gewünscht." in body
    assert "30 Pers., Buffet, Rückruf" in body
    assert "proposal-42" in body


def test_create_inquiry_intake_subject_shown_but_message_not_on_list_view(
    panel: str,
) -> None:
    """WEBSITE_FORM_INQUIRY_OFFICE_UX_PACK_V1 §4: intake_subject now appears
    (truncated) as the list's Betreff column — superseding the pre-pack
    behavior where no intake field appeared in the list at all. The other
    three intake fields (message/summary/external_ref) still stay
    detail-only, unchanged."""
    _iid = _create_inquiry(
        panel,
        intake_subject="Nur-Betreff-Test",
        intake_message="Nur-Detail-Message-Test",
    )
    _status, body = _get(f"{panel}/anfragen")
    assert "Nur-Betreff-Test" in body
    assert "Nur-Detail-Message-Test" not in body


def test_update_inquiry_sets_and_clears_intake_fields(panel: str) -> None:
    iid = _create_inquiry(panel, intake_subject="Erstfassung")
    _post(
        f"{panel}/inquiry/{iid}/update",
        {
            "event_date": "2026-10-01",
            "time_window_text": "mittags",
            "location_text": "Hamburg",
            "guest_count_estimate": "25",
            "planning_mode": "caterer_suggestion",
            "crm_stage": "Neue Anfrage",
            "intake_subject": "Zweitfassung",
            "intake_message": "",
            "intake_summary": "",
            "intake_external_ref": "",
        },
    )
    _status, body = _get(f"{panel}/inquiry/{iid}")
    assert "Zweitfassung" in body
    assert "Erstfassung" not in body


def test_creating_inquiry_with_intake_context_creates_no_order_or_orderversion() -> (
    None
):
    inquiry_repo = InMemoryInquiryRepository()
    order_repo = InMemoryOrderRepository()
    server = create_office_panel_server(
        inquiry_repo, order_repo, _PASSWORD, host="127.0.0.1", port=0
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        base = f"http://{host}:{port}"
        _create_inquiry(
            base,
            intake_subject="Betreff",
            intake_message="Nachricht",
            intake_summary="Zusammenfassung",
            intake_external_ref="ref-1",
        )
        assert len(inquiry_repo.list_all()) == 1
        assert order_repo.list_orders() == []
        assert order_repo._versions == {}  # noqa: SLF001 — no public "list all versions" method
    finally:
        server.shutdown()
        server.server_close()


def test_intake_context_does_not_change_wochenuebersicht() -> None:
    """Kiosk/Wochenübersicht output is byte-identical before/after an
    Inquiry with full intake context is created — WochenuebersichtService
    reads OrderVersion only, never Inquiry (07083cc §1's evidence)."""
    from catering_system.services.wochenuebersicht_service import (
        WochenuebersichtService,
    )

    inquiry_repo = InMemoryInquiryRepository()
    order_repo = InMemoryOrderRepository()
    panel = OfficePanel(inquiry_repo, order_repo)
    week = WochenuebersichtService(order_repo)
    before = week.get_week_overview(2026, 40)

    panel.create_inquiry(
        {
            "event_date": "2026-10-01",
            "inquiry_source": "manual",
            "time_window_text": "mittags",
            "location_text": "Hamburg",
            "guest_count_estimate": "25",
            "planning_mode": "caterer_suggestion",
            "intake_subject": "Betreff",
            "intake_message": "Nachricht",
            "intake_summary": "Zusammenfassung",
            "intake_external_ref": "ref-1",
        }
    )
    after = week.get_week_overview(2026, 40)
    assert after == before


def test_convert_inquiry_with_intake_context_does_not_leak_into_order(
    panel: str,
) -> None:
    """convert_inquiry_to_order must not turn intake_summary into
    OrderVersion.items — there is no such field to leak into, and this
    proves the conversion doesn't crash or invent one."""
    iid = _create_inquiry(
        panel,
        intake_subject="Betreff",
        intake_summary="2x Brötchen Mix, 10 Personen",
    )
    oid = _convert(panel, iid)
    status, body = _get(f"{panel}/order/{oid}")
    assert status == 200
    assert "2x Brötchen Mix, 10 Personen" not in body
    from dataclasses import fields

    from catering_system.domain.order import Order, OrderVersion

    assert not any(f.name.startswith("intake_") for f in fields(Order))
    assert not any(f.name.startswith("intake_") for f in fields(OrderVersion))


# -- orders -------------------------------------------------------------


def test_order_shows_operational_block_reasons(panel: str) -> None:
    iid = _create_inquiry(panel)
    oid = _convert(panel, iid)
    _status, body = _get(f"{panel}/order/{oid}")
    assert "Versandfreigabe blockiert" in body
    assert (
        "keine wirksame Auftragsversion" in body
    )  # operational vocabulary, human label, on order view
    assert (
        "Rückrufprüfung noch nicht erfüllt" not in body
    )  # vocabularies not merged (§5)


def test_effective_before_print_rejected(panel: str) -> None:
    iid = _create_inquiry(panel)
    oid = _convert(panel, iid)
    _status, body = _get(f"{panel}/order/{oid}")
    vid = body.split('name="order_version_id" value="')[1].split('"')[0]
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(f"{panel}/order/{oid}/effective", {"order_version_id": vid})
    assert exc.value.code == 400
    assert "kitchen print not confirmed" in exc.value.read().decode("utf-8")


def test_order_page_offers_effective_only_after_print_confirmation(panel: str) -> None:
    iid = _create_inquiry(panel)
    oid = _convert(panel, iid)
    _status, body = _get(f"{panel}/order/{oid}")
    vid = body.split('name="order_version_id" value="')[1].split('"')[0]
    assert f'action="/order/{oid}/print-confirm"' in body
    assert f'action="/order/{oid}/effective"' not in body
    assert "Wirksam machen" not in body

    _post(f"{panel}/order/{oid}/print-confirm", {"order_version_id": vid})
    assert _PANEL_JOBS[panel].list_for_version(vid)
    _status, body = _get(f"{panel}/order/{oid}")
    assert f'action="/order/{oid}/print-confirm"' in body
    assert f'action="/order/{oid}/effective"' not in body
    assert "Wirksam machen" not in body

    _simulate_kitchen_agent_ack(panel, vid)
    _status, body = _get(f"{panel}/order/{oid}")
    assert f'action="/order/{oid}/print-confirm"' not in body
    assert f'action="/order/{oid}/effective"' not in body
    assert "Wirksam machen" not in body
    assert "READY_TO_SEND: bereit" in body


def test_stale_print_attempt_offers_explicit_reprint(panel: str) -> None:
    iid = _create_inquiry(panel)
    oid = _convert(panel, iid)
    _status, body = _get(f"{panel}/order/{oid}")
    vid = body.split('name="order_version_id" value="')[1].split('"')[0]
    requested_at = datetime(2026, 7, 14, 9, 0, tzinfo=UTC)
    stale_job_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    _PANEL_JOBS[panel].save(
        KitchenPrintJob(
            print_job_id=stale_job_id,
            order_id=oid,
            order_version_id=vid,
            attempt_number=1,
            requested_at=requested_at,
            accept_deadline_at=requested_at + timedelta(seconds=30),
            accepted_at=requested_at + timedelta(seconds=1),
            ack_deadline_at=requested_at + timedelta(minutes=5),
        )
    )

    _status, body = _get(f"{panel}/order/{oid}")
    assert "Erneut drucken" in body

    _post(f"{panel}/order/{oid}/print-confirm", {"order_version_id": vid})

    attempts = _PANEL_JOBS[panel].list_for_version(vid)
    assert [attempt.attempt_number for attempt in attempts] == [1, 2]
    assert attempts[0].superseded_at is not None
    assert attempts[1].supersedes_print_job_id == stale_job_id


def test_unaccepted_expired_print_attempt_reprints_from_office(panel: str) -> None:
    iid = _create_inquiry(panel)
    oid = _convert(panel, iid)
    _status, body = _get(f"{panel}/order/{oid}")
    vid = body.split('name="order_version_id" value="')[1].split('"')[0]
    requested_at = datetime(2026, 7, 14, 9, 0, tzinfo=UTC)
    expired_job_id = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
    _PANEL_JOBS[panel].save(
        KitchenPrintJob(
            print_job_id=expired_job_id,
            order_id=oid,
            order_version_id=vid,
            attempt_number=1,
            requested_at=requested_at,
            accept_deadline_at=requested_at + timedelta(seconds=30),
        )
    )

    _status, body = _get(f"{panel}/order/{oid}")
    assert "Erneut drucken" in body
    assert "Druckauftrag nicht rechtzeitig angenommen." in body

    _post(f"{panel}/order/{oid}/print-confirm", {"order_version_id": vid})

    attempts = _PANEL_JOBS[panel].list_for_version(vid)
    assert [attempt.attempt_number for attempt in attempts] == [1, 2]
    assert attempts[0].superseded_at is not None
    assert attempts[1].supersedes_print_job_id == expired_job_id


def test_full_release_flow(panel: str) -> None:
    iid = _create_inquiry(panel)
    oid = _convert(panel, iid)
    _status, body = _get(f"{panel}/order/{oid}")
    vid = body.split('name="order_version_id" value="')[1].split('"')[0]
    _post(f"{panel}/order/{oid}/print-confirm", {"order_version_id": vid})
    _simulate_kitchen_agent_ack(panel, vid)
    _status, _url, body = _post(f"{panel}/order/{oid}/ready", {})
    assert "READY_TO_SEND: bereit" in body


def test_new_version_via_form(panel: str) -> None:
    iid = _create_inquiry(panel)
    oid = _convert(panel, iid)
    _status, _url, body = _post(
        f"{panel}/order/{oid}/version",
        {
            "event_date": "2026-10-03",
            "time_window_text": "früh",
            "location_text": "Lübeck",
            "guest_count_estimate": "40",
            "planning_mode": "caterer_suggestion",
        },
    )
    assert "v2" in body and "Lübeck" in body


def test_print_sheet_renders(panel: str) -> None:
    iid = _create_inquiry(panel)
    oid = _convert(panel, iid)
    _status, body = _get(f"{panel}/order/{oid}")
    vid = body.split("print?version=")[1].split('"')[0]
    status, sheet = _get(f"{panel}/order/{oid}/print?version={vid}")
    assert status == 200
    assert (
        "Küchenzettel" in sheet and "Hamburg" in sheet and "Bestellung / Menü" in sheet
    )


def test_cancel_shows_storniert_and_hides_actions(panel: str) -> None:
    iid = _create_inquiry(panel)
    oid = _convert(panel, iid)
    _status, _url, body = _post(f"{panel}/order/{oid}/cancel", {})
    assert "STORNIERT" in body
    assert "Auftrag stornieren" not in body  # actions hidden
    assert "Auftrag storniert" in body  # operational reason shown, human label
    assert "Küchenzettel" in body  # history stays viewable


def test_v2_order_detail_guides_print_effective_and_release(
    premium_panel: str,
) -> None:
    inquiry_id = _create_inquiry(premium_panel)
    _set_fulfillment_mode(premium_panel, inquiry_id, "PICKUP")
    order_id = _convert(premium_panel, inquiry_id)

    _status, initial = _get(f"{premium_panel}/order/{order_id}")
    version_id = re.search(r'name="order_version_id" value="([^"]+)"', initial).group(1)

    assert '<header class="order-header">' in initial
    assert '<section class="order-next-step">' in initial
    assert "<h1>Auftrag · Kunde nicht verfügbar</h1>" in initial
    assert "01.10.2026 · 25 Gäste" in initial
    assert "Küchenzettel für den aktuellen Stand drucken" in initial
    assert "Küchendruck starten" in initial
    assert f'action="/order/{order_id}/print-confirm"' in initial
    assert f'action="/order/{order_id}/effective"' not in initial
    assert "Als Küchenstand festlegen" not in initial
    assert "<h2>Veranstaltung</h2>" in initial
    assert "<h2>Kunde &amp; Lieferung</h2>" in initial
    assert "<h2>Bestellung</h2>" in initial
    assert "Seeded Menü" in initial
    assert '<details class="order-history">' in initial
    assert '<details class="order-lower-section order-more-actions">' in initial
    assert "READY_TO_SEND" not in initial

    _post(
        f"{premium_panel}/order/{order_id}/print-confirm",
        {"order_version_id": version_id},
    )
    _status, processing = _get(f"{premium_panel}/order/{order_id}")
    assert "Druckauftrag wird verarbeitet" in processing
    assert f'action="/order/{order_id}/print-confirm"' not in processing
    _simulate_kitchen_agent_ack(premium_panel, version_id)
    _status, printed = _get(f"{premium_panel}/order/{order_id}")

    assert "Vorbereitung vollständig" in printed
    assert '<section class="order-next-step complete">' in printed
    assert "Der Küchenstand ist bestätigt." in printed
    assert f'action="/order/{order_id}/print-confirm"' not in printed
    assert f'action="/order/{order_id}/effective"' not in printed

    assert f'action="/order/{order_id}/ready"' in printed

    visible = html.unescape(re.sub(r"<[^>]+>", " ", printed))
    assert order_id[:8] not in visible
    assert inquiry_id[:8] not in visible
    assert "caterer_suggestion" not in visible
    assert "READY_TO_SEND" not in visible


def test_v2_order_detail_promotes_confirmation_document_after_print_ready() -> None:
    now = datetime.now(UTC)
    order = Order(
        order_id="order-document-next-step",
        source_inquiry_id="inquiry-document-next-step",
        created_at=now,
        updated_at=now,
    )
    version = OrderVersion(
        order_version_id="version-document-next-step",
        order_id=order.order_id,
        version_number=1,
        created_at=now,
        event_date=date(2026, 10, 1),
        time_window_text="mittags",
        location_text="Hamburg",
        guest_count_estimate=25,
        planning_mode="caterer_suggestion",
        kitchen_print_confirmed_at=now,
    )
    forms = OrderDetailFormFields(
        csrf_input="",
        print_confirm_command_fields={},
        effective_command_fields={},
        ready_command_fields="",
        cancel_command_fields="",
        version_command_fields="",
        payment_command_fields="",
        confirmation_command_fields='<input type="hidden" name="_command_id" value="cmd-doc">',
    )

    detail = render_order_detail(
        order,
        [version],
        ReadyToSendEvaluation(order_id=order.order_id, ready=True, reasons=()),
        derive_payment_reminder(None, event_date=date(2026, 10, 1), today=date.today()),
        None,
        OrderConfirmationDocumentEligibility(
            available=True,
            state="bereit_zur_vorschau",
            can_prepare=True,
        ),
        OutboundSendEligibility(state="dokument_fehlt", can_send=False),
        forms,
        ConfirmationLivePreviewView(
            state="ready",
            preview=CustomerDocumentPreview(
                document_type="ORDER_CONFIRMATION",
                eligible=True,
                warnings=(),
                blockers=(),
                recipient=CustomerDocumentRecipient(name="Kunde"),
            ),
        ),
        source_inquiry=None,
        versions_total_count=1,
        versions_truncated=False,
        context=OfficePageContext(
            employee_effective_permissions=frozenset({"documents.prepare"})
        ),
    )
    next_step = _next_step_section(detail.body)
    status_card = _status_card_section(detail.body)

    assert "<h2>Auftragsbestätigung erstellen</h2>" in next_step
    assert f'action="/order/{order.order_id}/confirmation-document"' in next_step
    assert (
        detail.body.count(f'action="/order/{order.order_id}/confirmation-document"')
        == 1
    )
    assert f'action="/order/{order.order_id}/ready"' not in next_step
    assert (
        '<span class="order-header-badge status">Auftragsbestätigung erstellen</span>'
        in detail.body
    )
    assert "<strong>Auftragsbestätigung erstellen</strong>" in status_card
    assert "Vorbereitung vollständig" not in status_card


def test_v2_order_detail_prioritizes_missing_fulfillment_before_print(
    premium_panel: str,
) -> None:
    inquiry_id = _create_inquiry(premium_panel)
    order_id = _convert(premium_panel, inquiry_id)

    _status, body = _get(f"{premium_panel}/order/{order_id}")
    next_step = _next_step_section(body)
    status_card = _status_card_section(body)

    assert "<h2>Auftragsart festlegen</h2>" in next_step
    assert "Bitte auswählen, ob der Auftrag geliefert oder abgeholt wird." in next_step
    assert f'action="/inquiry/{inquiry_id}/fulfillment-mode"' in next_step
    assert '<option value="DELIVERY">Lieferung</option>' in next_step
    assert '<option value="PICKUP">Abholung</option>' in next_step
    assert "print-confirm" not in next_step
    assert "Küchenzettel für den aktuellen Stand drucken" not in next_step
    assert (
        '<span class="order-header-badge status">Auftragsart festlegen</span>' in body
    )
    assert "<strong>Auftragsart festlegen</strong>" in status_card
    assert "Küchendruck erforderlich" not in status_card


def test_v2_order_detail_prioritizes_delivery_address_for_delivery(
    premium_panel: str,
) -> None:
    inquiry_id = _create_inquiry(premium_panel)
    _set_fulfillment_mode(premium_panel, inquiry_id, "DELIVERY")
    order_id = _convert(premium_panel, inquiry_id)

    _status, body = _get(f"{premium_panel}/order/{order_id}")
    version_id = re.search(r'name="parent_order_version_id" value="([^"]+)"', body)
    next_step = _next_step_section(body)
    status_card = _status_card_section(body)

    assert "<h2>Lieferadresse ergänzen</h2>" in next_step
    assert "Für eine Lieferung muss eine Lieferadresse hinterlegt sein." in next_step
    assert f'action="/order/{order_id}/delivery-address"' in next_step
    assert body.count(f'action="/order/{order_id}/delivery-address"') == 1
    assert version_id is not None
    assert f'value="{version_id.group(1)}"' in next_step
    assert "print-confirm" not in next_step
    assert (
        '<span class="order-header-badge status">Lieferadresse ergänzen</span>' in body
    )
    assert "<strong>Lieferadresse ergänzen</strong>" in status_card
    assert "Küchendruck erforderlich" not in status_card


def test_v2_order_detail_pickup_and_delivery_with_address_allow_print(
    premium_panel: str,
) -> None:
    pickup_inquiry_id = _create_inquiry(premium_panel)
    _set_fulfillment_mode(premium_panel, pickup_inquiry_id, "PICKUP")
    pickup_order_id = _convert(premium_panel, pickup_inquiry_id)

    _status, pickup_body = _get(f"{premium_panel}/order/{pickup_order_id}")
    pickup_next_step = _next_step_section(pickup_body)
    pickup_status = _status_card_section(pickup_body)

    assert "<h2>Lieferadresse ergänzen</h2>" not in pickup_next_step
    assert "Küchenzettel für den aktuellen Stand drucken" in pickup_next_step
    assert f'action="/order/{pickup_order_id}/print-confirm"' in pickup_next_step
    assert f'action="/order/{pickup_order_id}/delivery-address"' in pickup_body
    assert (
        '<span class="order-header-badge status">Küchendruck erforderlich</span>'
        in pickup_body
    )
    assert "<strong>Küchendruck erforderlich</strong>" in pickup_status

    delivery_inquiry_id = _create_inquiry(premium_panel)
    _set_fulfillment_mode(premium_panel, delivery_inquiry_id, "DELIVERY")
    inquiries, orders, snapshots = _PANEL_REPOS[premium_panel]
    inquiry = inquiries.get_by_id(delivery_inquiry_id)
    assert inquiry is not None
    now = datetime.now(UTC)
    delivery_order_id = str(uuid.uuid4())
    delivery_version_id = str(uuid.uuid4())
    order = Order(
        order_id=delivery_order_id,
        source_inquiry_id=delivery_inquiry_id,
        created_at=now,
        updated_at=now,
    )
    version = OrderVersion(
        order_version_id=delivery_version_id,
        order_id=delivery_order_id,
        version_number=1,
        created_at=now,
        event_date=inquiry.event_date,
        time_window_text=inquiry.time_window_text,
        location_text=inquiry.location_text,
        guest_count_estimate=inquiry.guest_count_estimate,
        planning_mode=inquiry.planning_mode,
    )
    orders.save_order_with_initial_version(
        order,
        version,
        OrderVersionOperationalContextSnapshot(
            order_version_id=delivery_version_id,
            order_id=delivery_order_id,
            recipient_company="Lieferkunde GmbH",
            recipient_name="Lieferkunde",
            recipient_phone="040 123456",
            delivery_address=CustomerAddress(
                street="Lieferweg 12",
                postal_code="20095",
                city="Hamburg",
                country="Deutschland",
            ),
            created_at=now,
            source="initial_inquiry_snapshot",
        ),
    )
    seed_commercial_snapshot(snapshots, delivery_order_id)

    _status, delivery_body = _get(f"{premium_panel}/order/{delivery_order_id}")
    delivery_next_step = _next_step_section(delivery_body)
    delivery_status = _status_card_section(delivery_body)

    assert "<h2>Lieferadresse ergänzen</h2>" not in delivery_next_step
    assert "Küchenzettel für den aktuellen Stand drucken" in delivery_next_step
    assert f'action="/order/{delivery_order_id}/print-confirm"' in delivery_next_step
    assert (
        '<span class="order-header-badge status">Küchendruck erforderlich</span>'
        in delivery_body
    )
    assert "<strong>Küchendruck erforderlich</strong>" in delivery_status


def test_v2_order_detail_ready_false_without_action_stays_neutral(
    premium_panel: str,
) -> None:
    from dataclasses import replace

    inquiry_id = _create_inquiry(premium_panel)
    _set_fulfillment_mode(premium_panel, inquiry_id, "PICKUP")
    order_id = _convert(premium_panel, inquiry_id)
    _inquiries, orders, _snapshots = _PANEL_REPOS[premium_panel]
    version = orders.list_order_versions(order_id)[0]
    orders.update_order_version(
        replace(version, kitchen_print_confirmed_at=datetime.now(UTC))
    )

    _status, body = _get(f"{premium_panel}/order/{order_id}")

    assert '<section class="order-next-step muted">' in body
    assert "<h2>Auftragsdaten prüfen</h2>" in body
    assert "Noch kein Stand ist als aktueller Küchenstand festgelegt." in body
    assert "Vorbereitung vollständig" not in body
    assert f'action="/order/{order_id}/ready"' not in body


def test_v2_order_detail_renders_automatic_effective_transition_notice() -> None:
    now = datetime.now(UTC)
    order = Order(
        order_id="order-awaiting-auto-effective",
        source_inquiry_id="inquiry-awaiting-auto-effective",
        created_at=now,
        updated_at=now,
    )
    version = OrderVersion(
        order_version_id="version-awaiting-auto-effective",
        order_id=order.order_id,
        version_number=1,
        created_at=now,
        event_date=date(2026, 10, 1),
        time_window_text="mittags",
        location_text="Hamburg",
        guest_count_estimate=25,
        planning_mode="caterer_suggestion",
        kitchen_print_confirmed_at=now,
    )
    forms = OrderDetailFormFields(
        csrf_input="",
        print_confirm_command_fields={},
        effective_command_fields={},
        ready_command_fields="",
        cancel_command_fields="",
        version_command_fields="",
        payment_command_fields="",
    )

    detail = render_order_detail(
        order,
        [version],
        ReadyToSendEvaluation(
            order_id=order.order_id,
            ready=False,
            reasons=("no_effective_version",),
        ),
        derive_payment_reminder(None, event_date=date(2026, 10, 1), today=date.today()),
        {"action": "effective", "order_version_id": version.order_version_id},
        OrderConfirmationDocumentEligibility(
            available=False,
            state="nicht_verfuegbar",
        ),
        OutboundSendEligibility(
            state="dokument_fehlt",
            can_send=False,
        ),
        forms,
        ConfirmationLivePreviewView(state="not_found"),
        versions_total_count=1,
        versions_truncated=False,
    )

    assert "Küchenstand wird automatisch übernommen" in detail.body
    assert "ohne weiteren manuellen Schritt" in detail.body
    assert f'action="/order/{order.order_id}/effective"' not in detail.body
    assert "Als Küchenstand festlegen" not in detail.body


def test_v2_order_detail_without_versions_stays_review_only() -> None:
    now = datetime.now(UTC)
    order = Order(
        order_id="order-without-versions",
        source_inquiry_id="inquiry-without-versions",
        created_at=now,
        updated_at=now,
    )
    forms = OrderDetailFormFields(
        csrf_input="",
        print_confirm_command_fields={},
        effective_command_fields={},
        ready_command_fields="",
        cancel_command_fields="",
        version_command_fields="",
        payment_command_fields="",
    )

    detail = render_order_detail(
        order,
        [],
        ReadyToSendEvaluation(
            order_id=order.order_id,
            ready=False,
            reasons=("effective_version_not_resolvable",),
        ),
        derive_payment_reminder(None, event_date=date(2026, 10, 1), today=date.today()),
        None,
        OrderConfirmationDocumentEligibility(
            available=False,
            state="nicht_verfuegbar",
        ),
        OutboundSendEligibility(
            state="dokument_fehlt",
            can_send=False,
        ),
        forms,
        ConfirmationLivePreviewView(state="not_found"),
        versions_total_count=0,
        versions_truncated=False,
    )

    assert "Veranstaltungsdaten nicht verfügbar" in detail.body
    assert "Für diesen Auftrag ist kein gültiger Stand verfügbar." in detail.body
    assert "Keine Auftragsstände vorhanden." in detail.body
    assert "Vorbereitung vollständig" not in detail.body
    assert "Küchendruck starten" not in detail.body


def test_v2_order_detail_pause_and_cancel_outprioritize_missing_fulfillment() -> None:
    now = datetime.now(UTC)
    order = Order(
        order_id="order-priority-paused",
        source_inquiry_id="inquiry-priority-paused",
        created_at=now,
        updated_at=now,
    )
    version = OrderVersion(
        order_version_id="version-priority-paused",
        order_id=order.order_id,
        version_number=1,
        created_at=now,
        event_date=date(2026, 10, 1),
        time_window_text="mittags",
        location_text="Hamburg",
        guest_count_estimate=25,
        planning_mode="caterer_suggestion",
    )
    inquiry = intake_from_website_form(
        InquiryService(InMemoryInquiryRepository()),
        {
            "event_date": date(2026, 10, 1),
            "location_text": "Hamburg",
            "guest_count_estimate": 25,
            "company": "Priorität GmbH",
            "email": "kunde@example.com",
            "phone": "040 123456",
            "submission_id": "priority-unknown",
        },
    )
    forms = OrderDetailFormFields(
        csrf_input="",
        print_confirm_command_fields={version.order_version_id: ""},
        effective_command_fields={},
        ready_command_fields="",
        cancel_command_fields="",
        version_command_fields="",
        payment_command_fields="",
    )

    paused = render_order_detail(
        order,
        [version],
        ReadyToSendEvaluation(
            order_id=order.order_id,
            ready=False,
            reasons=("operational_pause",),
        ),
        derive_payment_reminder(None, event_date=date(2026, 10, 1), today=date.today()),
        {"action": "print-confirm", "order_version_id": version.order_version_id},
        OrderConfirmationDocumentEligibility(available=False, state="nicht_verfuegbar"),
        OutboundSendEligibility(state="dokument_fehlt", can_send=False),
        forms,
        ConfirmationLivePreviewView(state="not_found"),
        source_inquiry=inquiry,
        operational_pause={"active": True, "reason_code": "customer_clarification"},
        versions_total_count=1,
        versions_truncated=False,
        context=OfficePageContext(
            employee_effective_permissions=frozenset({"orders.pause"})
        ),
    )

    assert "Auftragspause klären" in paused.body
    assert '<span class="order-header-badge status">Pausiert</span>' in paused.body
    assert "<strong>Betrieblich pausiert</strong>" in _status_card_section(paused.body)
    assert "Auftragsart festlegen" not in _next_step_section(paused.body)
    assert "print-confirm" not in _next_step_section(paused.body)

    cancelled = render_order_detail(
        Order(
            order_id="order-priority-cancelled",
            source_inquiry_id=inquiry.inquiry_id,
            created_at=now,
            updated_at=now,
            cancelled_at=now,
        ),
        [version],
        ReadyToSendEvaluation(
            order_id="order-priority-cancelled",
            ready=False,
            reasons=("order_cancelled",),
        ),
        derive_payment_reminder(None, event_date=date(2026, 10, 1), today=date.today()),
        {"action": "print-confirm", "order_version_id": version.order_version_id},
        OrderConfirmationDocumentEligibility(available=False, state="nicht_verfuegbar"),
        OutboundSendEligibility(state="dokument_fehlt", can_send=False),
        forms,
        ConfirmationLivePreviewView(state="not_found"),
        source_inquiry=inquiry,
        versions_total_count=1,
        versions_truncated=False,
        context=legacy_office_context(),
    )

    assert "Keine weitere Bearbeitung" in cancelled.body
    assert '<span class="order-header-badge status">Storniert</span>' in cancelled.body
    assert "<strong>Auftrag storniert</strong>" in _status_card_section(cancelled.body)
    assert "Auftragsart festlegen" not in _next_step_section(cancelled.body)
    assert "print-confirm" not in _next_step_section(cancelled.body)


def test_v2_order_detail_hides_unauthorized_priority_actions() -> None:
    now = datetime.now(UTC)
    order = Order(
        order_id="order-priority-permissions",
        source_inquiry_id="inquiry-priority-permissions",
        created_at=now,
        updated_at=now,
    )
    version = OrderVersion(
        order_version_id="version-priority-permissions",
        order_id=order.order_id,
        version_number=1,
        created_at=now,
        event_date=date(2026, 10, 1),
        time_window_text="mittags",
        location_text="Hamburg",
        guest_count_estimate=25,
        planning_mode="caterer_suggestion",
    )
    inquiry = intake_from_website_form(
        InquiryService(InMemoryInquiryRepository()),
        {
            "event_date": date(2026, 10, 1),
            "location_text": "Hamburg",
            "guest_count_estimate": 25,
            "company": "Rechte GmbH",
            "email": "kunde@example.com",
            "phone": "040 123456",
            "submission_id": "priority-permissions",
        },
    )
    forms = OrderDetailFormFields(
        csrf_input="",
        print_confirm_command_fields={version.order_version_id: ""},
        effective_command_fields={},
        ready_command_fields="",
        cancel_command_fields="",
        version_command_fields="",
        payment_command_fields="",
        confirmation_command_fields="",
    )

    no_inquiry_edit = render_order_detail(
        order,
        [version],
        ReadyToSendEvaluation(
            order_id=order.order_id,
            ready=False,
            reasons=("kitchen_print_not_confirmed",),
        ),
        derive_payment_reminder(None, event_date=date(2026, 10, 1), today=date.today()),
        {"action": "print-confirm", "order_version_id": version.order_version_id},
        OrderConfirmationDocumentEligibility(available=False, state="nicht_verfuegbar"),
        OutboundSendEligibility(state="dokument_fehlt", can_send=False),
        forms,
        ConfirmationLivePreviewView(state="not_found"),
        source_inquiry=inquiry,
        versions_total_count=1,
        versions_truncated=False,
        context=OfficePageContext(
            employee_effective_permissions=frozenset({"orders.print.confirm"})
        ),
    )
    no_inquiry_edit_next = _next_step_section(no_inquiry_edit.body)

    assert "Auftragsart festlegen" in no_inquiry_edit_next
    assert "fulfillment-mode" not in no_inquiry_edit_next
    assert "print-confirm" not in no_inquiry_edit_next

    no_documents_prepare = render_order_detail(
        order,
        [version],
        ReadyToSendEvaluation(order_id=order.order_id, ready=True, reasons=()),
        derive_payment_reminder(None, event_date=date(2026, 10, 1), today=date.today()),
        None,
        OrderConfirmationDocumentEligibility(
            available=True,
            state="bereit_zur_vorschau",
            can_prepare=True,
        ),
        OutboundSendEligibility(state="dokument_fehlt", can_send=False),
        forms,
        ConfirmationLivePreviewView(
            state="ready",
            preview=CustomerDocumentPreview(
                document_type="ORDER_CONFIRMATION",
                eligible=True,
                warnings=(),
                blockers=(),
                recipient=CustomerDocumentRecipient(name="Kunde"),
            ),
        ),
        source_inquiry=None,
        versions_total_count=1,
        versions_truncated=False,
        context=OfficePageContext(employee_effective_permissions=frozenset()),
    )
    no_documents_prepare_next = _next_step_section(no_documents_prepare.body)
    no_documents_prepare_status = _status_card_section(no_documents_prepare.body)

    assert "Auftragsbestätigung prüfen" in no_documents_prepare_next
    assert "Auftragsbestätigung erstellen" not in no_documents_prepare_next
    assert "Vorbereitung vollständig" not in no_documents_prepare_next
    assert "Auftragsbestätigung erstellen" in no_documents_prepare_status
    assert "Vorbereitung vollständig" not in no_documents_prepare_status


def test_v2_order_detail_uses_exact_target_delivery_address(
    premium_panel: str,
) -> None:
    inquiry_id = _create_inquiry(
        premium_panel,
        company_name="Live Inquiry GmbH",
        contact_name="Live Contact",
    )
    inquiries, orders, snapshots = _PANEL_REPOS[premium_panel]
    inquiry_service = InquiryService(inquiries)
    live_address = CustomerAddress(
        street="Liveweg 9",
        postal_code="10115",
        city="Berlin",
        country="Deutschland",
    )
    inquiry_service.set_inquiry_customer_addresses(
        inquiry_id,
        invoice_address=live_address,
        delivery_address=live_address,
        delivery_address_mode="SEPARATE",
    )
    inquiry_service.set_inquiry_fulfillment_mode(
        inquiry_id, fulfillment_mode="DELIVERY"
    )
    inquiry = inquiries.get_by_id(inquiry_id)
    assert inquiry is not None
    now = datetime.now(UTC)
    order_id = str(uuid.uuid4())
    version_id = str(uuid.uuid4())
    order = Order(
        order_id=order_id,
        source_inquiry_id=inquiry_id,
        created_at=now,
        updated_at=now,
    )
    version = OrderVersion(
        order_version_id=version_id,
        order_id=order_id,
        version_number=1,
        created_at=now,
        event_date=inquiry.event_date,
        time_window_text=inquiry.time_window_text,
        location_text=inquiry.location_text,
        guest_count_estimate=inquiry.guest_count_estimate,
        planning_mode=inquiry.planning_mode,
    )
    exact_address = CustomerAddress(
        street="Musterstraße 1",
        postal_code="20095",
        city="Hamburg",
        country="Deutschland",
    )
    context = OrderVersionOperationalContextSnapshot(
        order_version_id=version_id,
        order_id=order_id,
        recipient_company="Grant Hotel",
        recipient_name="Fr. Garent",
        recipient_phone="+4940235649",
        delivery_address=exact_address,
        created_at=now,
        source="initial_inquiry_snapshot",
    )
    orders.save_order_with_initial_version(order, version, context)
    seed_commercial_snapshot(snapshots, order_id)

    _status, body = _get(f"{premium_panel}/order/{order_id}")

    assert "Auftrag · Grant Hotel" in body
    assert "Musterstraße 1" in body
    assert "20095 Hamburg" in body
    assert "+4940235649" in body
    assert "Liveweg 9" not in body
    assert "effektive Lieferadresse" not in body
    assert "gespeicherte Lieferadresse" not in body


def test_v2_order_detail_never_falls_back_to_live_inquiry_delivery_address(
    premium_panel: str,
) -> None:
    inquiry_id = _create_inquiry(premium_panel)
    inquiries, _orders, _snapshots = _PANEL_REPOS[premium_panel]
    live_address = CustomerAddress(
        street="Nur-in-der-Anfrage 7",
        postal_code="24103",
        city="Kiel",
        country="Deutschland",
    )
    InquiryService(inquiries).set_inquiry_customer_addresses(
        inquiry_id,
        invoice_address=live_address,
        delivery_address=live_address,
        delivery_address_mode="SEPARATE",
    )
    order_id = _convert(premium_panel, inquiry_id)

    _status, body = _get(f"{premium_panel}/order/{order_id}")
    customer_section = body.split("<h2>Kunde &amp; Lieferung</h2>", 1)[1].split(
        "</section>", 1
    )[0]

    assert "Nur-in-der-Anfrage 7" not in body
    assert "Lieferadresse" in customer_section
    assert "Nicht verfügbar" in customer_section


def test_v2_order_detail_prefers_new_candidate_over_ready_old_stand(
    premium_panel: str,
) -> None:
    inquiry_id = _create_inquiry(premium_panel)
    _set_fulfillment_mode(premium_panel, inquiry_id, "PICKUP")
    order_id = _convert(premium_panel, inquiry_id)
    _status, initial = _get(f"{premium_panel}/order/{order_id}")
    version_id = re.search(r'name="order_version_id" value="([^"]+)"', initial).group(1)
    _post(
        f"{premium_panel}/order/{order_id}/print-confirm",
        {"order_version_id": version_id},
    )
    _simulate_kitchen_agent_ack(premium_panel, version_id)
    _post(
        f"{premium_panel}/order/{order_id}/effective",
        {"order_version_id": version_id},
    )
    _status, before_change = _get(f"{premium_panel}/order/{order_id}")
    latest_version_number = re.search(
        r'name="latest_version_number" value="([^"]+)"',
        before_change,
    ).group(1)
    assert 'value="2026-10-01"' in before_change
    assert 'value="mittags"' in before_change
    assert 'value="Hamburg"' in before_change
    _post(
        f"{premium_panel}/order/{order_id}/version",
        {
            "latest_version_number": latest_version_number,
            "event_date": "2026-10-03",
            "time_window_text": "18:00–22:00",
            "location_text": "Hamburg-Altona",
            "guest_count_estimate": "40",
            "planning_mode": "self_select",
        },
    )

    _status, body = _get(f"{premium_panel}/order/{order_id}")

    assert "03.10.2026 · 40 Gäste" in body
    assert "Küchenzettel für den aktuellen Stand drucken" in body
    assert "Hamburg-Altona" in body
    assert "Auswahl durch den Kunden" in body
    assert "Nächster Stand" in body
    assert "Eine Änderung wartet noch auf Küchendruck" in body
    assert "Aktueller Küchenstand" in body
    assert "Aktueller Bearbeitungsstand" in body


def test_v2_stale_print_ack_shows_human_warning_without_manual_effective_action(
    premium_panel: str,
) -> None:
    inquiry_id = _create_inquiry(premium_panel)
    order_id = _convert(premium_panel, inquiry_id)
    _status, initial = _get(f"{premium_panel}/order/{order_id}")
    v1_id = re.search(r'name="order_version_id" value="([^"]+)"', initial).group(1)
    _post(
        f"{premium_panel}/order/{order_id}/print-confirm", {"order_version_id": v1_id}
    )
    _simulate_kitchen_agent_ack(premium_panel, v1_id)

    _status, before_v2 = _get(f"{premium_panel}/order/{order_id}")
    latest_version_number = re.search(
        r'name="latest_version_number" value="([^"]+)"',
        before_v2,
    ).group(1)
    _post(
        f"{premium_panel}/order/{order_id}/version",
        {
            "latest_version_number": latest_version_number,
            "event_date": "2026-10-02",
            "time_window_text": "abends",
            "location_text": "Kiel",
            "guest_count_estimate": "30",
            "planning_mode": "caterer_suggestion",
        },
    )
    _status, v2_page = _get(f"{premium_panel}/order/{order_id}")
    v2_id = re.search(r'name="order_version_id" value="([^"]+)"', v2_page).group(1)
    _post(
        f"{premium_panel}/order/{order_id}/print-confirm", {"order_version_id": v2_id}
    )

    latest_version_number = re.search(
        r'name="latest_version_number" value="([^"]+)"',
        v2_page,
    ).group(1)
    _post(
        f"{premium_panel}/order/{order_id}/version",
        {
            "latest_version_number": latest_version_number,
            "event_date": "2026-10-03",
            "time_window_text": "mittags",
            "location_text": "Lübeck",
            "guest_count_estimate": "40",
            "planning_mode": "self_select",
        },
    )

    _simulate_kitchen_agent_ack(premium_panel, v2_id)
    _status, body = _get(f"{premium_panel}/order/{order_id}")

    assert "Küchendruck nicht übernommen" in body
    assert "inzwischen gibt es einen neueren Stand" in body
    assert f'action="/order/{order_id}/effective"' not in body
    assert "Wirksam machen" not in body


def test_v2_create_version_rejects_stale_latest_version_number(
    premium_panel: str,
) -> None:
    inquiry_id = _create_inquiry(premium_panel)
    order_id = _convert(premium_panel, inquiry_id)
    _status, initial = _get(f"{premium_panel}/order/{order_id}")
    latest_version_number = re.search(
        r'name="latest_version_number" value="([^"]+)"',
        initial,
    ).group(1)
    _post(
        f"{premium_panel}/order/{order_id}/version",
        {
            "latest_version_number": latest_version_number,
            "event_date": "2026-10-02",
            "time_window_text": "abends",
            "location_text": "Kiel",
            "guest_count_estimate": "30",
            "planning_mode": "caterer_suggestion",
        },
    )
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(
            f"{premium_panel}/order/{order_id}/version",
            {
                "latest_version_number": latest_version_number,
                "event_date": "2026-10-03",
                "time_window_text": "spät",
                "location_text": "Lübeck",
                "guest_count_estimate": "35",
                "planning_mode": "caterer_suggestion",
            },
        )
    assert exc.value.code == 400
    assert "zwischenzeitlich geändert" in exc.value.read().decode("utf-8")


def test_v2_order_detail_keeps_payment_separate_and_cancelled_read_only(
    premium_panel: str,
) -> None:
    inquiry_id = _create_inquiry(premium_panel)
    _set_fulfillment_mode(premium_panel, inquiry_id, "PICKUP")
    order_id = _convert(premium_panel, inquiry_id)

    _post(
        f"{premium_panel}/order/{order_id}/payment-reminder",
        {
            "payment_method": "RECHNUNG",
            "invoice_created": "1",
            "invoice_number": "RE-UI4-1",
            "sent_on": "2026-07-15",
            "due_on": "2026-10-01",
        },
    )
    _status, body = _get(f"{premium_panel}/order/{order_id}")

    assert "order-payment-card" in body
    assert "<h2>Zahlung</h2>" in body
    assert "Zahlungserinnerung senden" in body
    assert "Reminder-Status" in body
    assert "RE-UI4-1" in body
    assert f'action="/order/{order_id}/payment-reminder"' in body
    assert f'action="/order/{order_id}/payment-method"' in body
    assert "Zahlungsart ändern" in body
    assert "Küchenzettel für den aktuellen Stand drucken" in body

    _post(
        f"{premium_panel}/order/{order_id}/payment-method",
        {
            "new_payment_method": "BAR_VOR_ORT",
            "reason": "Kunde zahlt bei Abholung bar",
        },
    )
    _status, changed = _get(f"{premium_panel}/order/{order_id}")
    assert "Bar vor Ort" in changed
    assert "Quittung vorbereiten/drucken" in changed
    assert "Zahlungsarten-Historie (1)" in changed
    assert "Rechnung → Bar vor Ort" in changed
    assert "Kunde zahlt bei Abholung bar" in changed
    assert "RE-UI4-1" in changed

    _post(f"{premium_panel}/order/{order_id}/cancel", {})
    _status, cancelled = _get(f"{premium_panel}/order/{order_id}")

    assert "Storniert" in cancelled
    assert "Keine weitere Bearbeitung" in cancelled
    assert "RE-UI4-1" in cancelled
    assert f"/order/{order_id}/print?version=" in cancelled
    for action in (
        "print-confirm",
        "effective",
        "ready",
        "cancel",
        "version",
        "payment-reminder",
        "payment-method",
    ):
        assert f'action="/order/{order_id}/{action}"' not in cancelled


def test_v2_order_detail_payment_correction_keeps_visible_history(
    premium_panel: str,
) -> None:
    inquiry_id = _create_inquiry(premium_panel)
    _set_fulfillment_mode(premium_panel, inquiry_id, "PICKUP")
    order_id = _convert(premium_panel, inquiry_id)

    _post(
        f"{premium_panel}/order/{order_id}/payment-reminder",
        {
            "payment_method": "RECHNUNG",
            "invoice_created": "1",
            "invoice_number": "RE-UI-CORR-1",
            "sent_on": "2026-07-01",
            "paid_on": "2026-07-15",
        },
    )
    _status, paid = _get(f"{premium_panel}/order/{order_id}")
    assert "Zahlungsstatus korrigieren" in paid
    assert f'action="/order/{order_id}/payment-correction"' in paid

    _post(
        f"{premium_panel}/order/{order_id}/payment-correction",
        {"reason": "Zahlung war eine Fehleingabe"},
    )
    _status, corrected = _get(f"{premium_panel}/order/{order_id}")

    assert "Zahlungskorrekturen (1)" in corrected
    assert "Zahlungsbestätigung korrigiert" in corrected
    assert "Zahlung war eine Fehleingabe" in corrected
    assert "15.07.2026" in corrected
    assert "Zahlungsstatus korrigieren" not in corrected


def test_v2_order_detail_escapes_hostile_facts_and_hides_technical_values(
    premium_panel: str,
) -> None:
    inquiry_id = _create_inquiry(premium_panel)
    order_id = _convert(premium_panel, inquiry_id)
    _post(
        f"{premium_panel}/order/{order_id}/version",
        {
            "event_date": "2026-10-03",
            "time_window_text": '<img src=x onerror="alert(1)">',
            "location_text": "<script>alert('location')</script>",
            "guest_count_estimate": "40",
            "planning_mode": "self_select",
        },
    )

    _status, body = _get(f"{premium_panel}/order/{order_id}")
    visible = html.unescape(re.sub(r"<[^>]+>", " ", body))

    assert "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;" in body
    assert "&lt;script&gt;alert(&#x27;location&#x27;)&lt;/script&gt;" in body
    assert '<img src=x onerror="alert(1)">' not in body
    assert "<script>alert" not in body
    assert order_id[:8] not in visible
    assert inquiry_id[:8] not in visible
    assert "self_select" not in visible
    assert "no_effective_version" not in visible
    assert "candidate_order_version_id" not in visible
    assert "Hanseatic Consulting" not in body
    assert "<script" not in body


def test_queue_shows_storniert_card_only_after_a_cancellation(panel: str) -> None:
    iid = _create_inquiry(panel)
    oid = _convert(panel, iid)
    _post(f"{panel}/order/{oid}/cancel", {})
    _status, body = _get(f"{panel}/")
    assert _attention_counts(body)["Stornierte Aufträge prüfen"] == 1
    # Cancelled orders drop out of the "next step" queue — nothing to act on.
    queue_html = body.split("Aufträge mit nächstem Schritt")[1]
    assert oid[:8] not in queue_html


def test_cancelled_actions_rejected_serverside(panel: str) -> None:
    """Hiding buttons is presentation; the gate itself must still refuse (§1: no panel-side logic)."""
    iid = _create_inquiry(panel)
    oid = _convert(panel, iid)
    _status, body = _get(f"{panel}/order/{oid}")
    vid = body.split('name="order_version_id" value="')[1].split('"')[0]
    _post(f"{panel}/order/{oid}/cancel", {})
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(f"{panel}/order/{oid}/print-confirm", {"order_version_id": vid})
    assert exc.value.code == 400


def test_cancelled_print_sheet_shows_storniert_banner(panel: str) -> None:
    iid = _create_inquiry(panel)
    oid = _convert(panel, iid)
    _status, body = _get(f"{panel}/order/{oid}")
    vid = body.split("print?version=")[1].split('"')[0]
    _post(f"{panel}/order/{oid}/cancel", {})
    _status, sheet = _get(f"{panel}/order/{oid}/print?version={vid}")
    assert "STORNIERT" in sheet  # kitchen must see the cancellation on the sheet


def test_convert_after_storno_returns_existing_order(panel: str) -> None:
    """Order existence remains authoritative — Storno does not unlock a second Order."""
    iid = _create_inquiry(panel)
    oid = _convert(panel, iid)
    _post(f"{panel}/order/{oid}/cancel", {})
    _status, body = _get(f"{panel}/inquiry/{iid}")
    assert "(storniert)" in body
    assert "Auftrag erstellen" not in body
    assert "Auftrag öffnen" in body
    # Compatibility POST convert returns the existing Order (no second create).
    _status, url, _body = _post(f"{panel}/inquiry/{iid}/convert", {})
    assert url.rsplit("/", 1)[-1] == oid
    _status, body = _get(f"{panel}/inquiry/{iid}")
    assert "Auftrag erstellen" not in body


def test_xss_escaped_in_views(panel: str) -> None:
    iid = _create_inquiry(panel, location_text='<script>alert("x")</script>')
    _status, body = _get(f"{panel}/inquiry/{iid}")
    assert "<script>alert" not in body
    assert "&lt;script&gt;" in body


def test_panel_serves_sqlite_like_on_lenovo(tmp_path) -> None:
    """Regression (bring-up bug): sqlite repos + server built in the serving thread,
    full write flow over HTTP must not hit sqlite3 cross-thread errors."""
    import queue

    from catering_system.repositories.sqlite_inquiry_repository import (
        SQLiteInquiryRepository,
    )
    from catering_system.repositories.sqlite_order_repository import (
        SQLiteOrderRepository,
    )

    db = tmp_path / "core.db"
    ready: queue.Queue = queue.Queue()

    def run() -> None:  # mirrors main()
        server = create_office_panel_server(
            SQLiteInquiryRepository(db),
            SQLiteOrderRepository(db),
            _PASSWORD,
            host="127.0.0.1",
            port=0,
        )
        ready.put(server)
        server.serve_forever()

    threading.Thread(target=run, daemon=True).start()
    server = ready.get(timeout=5)
    host, port = server.server_address[:2]
    base = f"http://{host}:{port}"
    try:
        iid = _create_inquiry(base)  # POST → sqlite write over HTTP
        inquiries = SQLiteInquiryRepository(db)
        orders = SQLiteOrderRepository(db)
        inquiry = inquiries.get_by_id(iid)
        assert inquiry is not None
        order, _version = seed_order(orders, inquiry)
        oid = order.order_id
        inquiries.close()
        orders.close()
        status, body = _get(f"{base}/order/{oid}")
        assert status == 200 and "v1" in body
    finally:
        server.shutdown()
        server.server_close()


def test_unknown_paths_404(panel: str) -> None:
    for path in ("/admin", "/inquiry/does-not-exist", "/order/does-not-exist"):
        with pytest.raises(urllib.error.HTTPError) as exc:
            _get(f"{panel}{path}")
        assert exc.value.code == 404


# -- Rückrufe: read-only pull from a stubbed auerswald-sync -----------------
# auerswald-sync is a separate, real service (own repo/server) that is NOT
# part of this codebase; these tests stand in a minimal stub for its
# /missed-board.json and /missed/resolve so the office panel's read-only
# integration can be exercised without a live auerswald-sync instance.

_AUERSWALD_ITEMS = [
    {
        "call_id": "07.07.26|09:00:00|+491234",
        "date": "07.07.26",
        "time": "09:00:00",
        "duration": "00:00:12",
        "phone": "01234",
        "normalized_phone": "+491234",
        "contact_found": False,
        "contact_name": "Unbekannt",
        "contact_url": "",
        "reason": "Nicht angenommen",
    }
]


def _make_auerswald_stub(
    resolved: list,
    hits: list | None = None,
    *,
    board_items: list[dict] | None = None,
) -> HTTPServer:
    items_source = _AUERSWALD_ITEMS if board_items is None else board_items

    class StubHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            pass

        def do_GET(self) -> None:  # noqa: N802
            if self.path.startswith("/missed-board.json"):
                if hits is not None:
                    hits.append(self.path)
                # Mirrors the real auerswald-sync: resolved calls drop out of
                # the board on the next fetch (build_missed_board_items()
                # excludes resolved_call_ids).
                remaining = [it for it in items_source if it["call_id"] not in resolved]
                payload = json.dumps({"items": remaining}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            else:
                self.send_error(404)

        def do_POST(self) -> None:  # noqa: N802
            if self.path == "/missed/resolve":
                length = int(self.headers.get("Content-Length", "0"))
                form = urllib.parse.parse_qs(self.rfile.read(length).decode())
                resolved.append(form["call_id"][0])
                self.send_response(303)
                self.send_header("Location", "/missed-board")
                self.end_headers()
            else:
                self.send_error(404)

    return HTTPServer(("127.0.0.1", 0), StubHandler)


def test_rueckruf_not_configured_shows_message_not_crash(panel: str) -> None:
    status, body = _get(f"{panel}/rueckruf")
    assert status == 200
    assert "nicht erreichbar" in body or "nicht konfiguriert" in body


def test_rueckruf_unreachable_url_shows_error_not_crash() -> None:
    inquiry_repo = InMemoryInquiryRepository()
    order_repo = InMemoryOrderRepository()
    # Port 1 is reserved/unroutable — guaranteed connection failure, no live server needed.
    server = create_office_panel_server(
        inquiry_repo,
        order_repo,
        _PASSWORD,
        host="127.0.0.1",
        port=0,
        auerswald_url="http://127.0.0.1:1",
        auerswald_user="u",
        auerswald_password="p",
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        status, body = _get(f"http://{host}:{port}/rueckruf")
        assert status == 200
        assert "nicht erreichbar" in body
    finally:
        server.shutdown()
        server.server_close()


def test_rueckruf_lists_items_from_auerswald_stub() -> None:
    resolved: list = []
    stub = _make_auerswald_stub(resolved)
    stub_thread = threading.Thread(target=stub.serve_forever, daemon=True)
    stub_thread.start()
    stub_host, stub_port = stub.server_address[:2]

    inquiry_repo = InMemoryInquiryRepository()
    order_repo = InMemoryOrderRepository()
    server = create_office_panel_server(
        inquiry_repo,
        order_repo,
        _PASSWORD,
        host="127.0.0.1",
        port=0,
        auerswald_url=f"http://{stub_host}:{stub_port}",
        auerswald_user="office",
        auerswald_password="secret",
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    base = f"http://{host}:{port}"
    try:
        status, body = _get(f"{base}/rueckruf")
        assert status == 200
        assert "Nicht angenommen" in body
        assert "01234" in body

        # Resolve action forwards to auerswald-sync's own endpoint, redirects back.
        status, final_url, body = _post(
            f"{base}/rueckruf/resolve", {"call_id": _AUERSWALD_ITEMS[0]["call_id"]}
        )
        assert status == 200 and final_url == f"{base}/rueckruf"
        assert resolved == [_AUERSWALD_ITEMS[0]["call_id"]]
    finally:
        server.shutdown()
        server.server_close()
        stub.shutdown()
        stub.server_close()


def test_rueckruf_resolves_local_core_contact_over_auerswald_name() -> None:
    from catering_system.services.inquiry_service import InquiryService

    board_items = [
        {
            **_AUERSWALD_ITEMS[0],
            "phone": "017642795029",
            "normalized_phone": "+4917642795029",
            "contact_found": True,
            "contact_name": "Auerswald Wrong Name",
            "contact_url": "https://example.invalid/contact",
        }
    ]
    resolved: list = []
    stub = _make_auerswald_stub(resolved, board_items=board_items)
    stub_thread = threading.Thread(target=stub.serve_forever, daemon=True)
    stub_thread.start()
    stub_host, stub_port = stub.server_address[:2]

    inquiry_repo = InMemoryInquiryRepository()
    order_repo = InMemoryOrderRepository()
    InquiryService(inquiry_repo).create_inquiry(
        event_date=date(2026, 8, 1),
        inquiry_source="manual",
        crm_stage="Neue Anfrage",
        customer_linkage={},
        time_window_text="mittags",
        location_text="Hamburg",
        guest_count_estimate=25,
        planning_mode="caterer_suggestion",
        call_verification_required=False,
        call_verification_status="not_required",
        intake_message="Firma: JK-art\nTelefon: +4917642795029\n",
    )
    server = create_office_panel_server(
        inquiry_repo,
        order_repo,
        _PASSWORD,
        host="127.0.0.1",
        port=0,
        auerswald_url=f"http://{stub_host}:{stub_port}",
        auerswald_user="office",
        auerswald_password="secret",
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    base = f"http://{host}:{port}"
    try:
        status, body = _get(f"{base}/rueckruf")
        assert status == 200
        assert ">JK-art</a>" in body
        assert 'href="/kontakt/intake%3Aphone%3A%2B4917642795029"' in body
        assert "Auerswald Wrong Name" not in body
        assert "Unbekannt" not in body
    finally:
        server.shutdown()
        server.server_close()
        stub.shutdown()
        stub.server_close()


# -- Dashboard: Heute-Aufmerksamkeit, Blocker column, Diese Woche, Suche ----
# All derived from data already fetched for the existing tables — no new
# domain concepts, matches pack §1 ("adds no domain semantics").


def _attention_counts(body: str) -> dict[str, int]:
    return {
        m.group(2): int(m.group(1))
        for m in re.finditer(r"<strong>(\d+)</strong>\s*([^<]+)", body)
    }


def test_queue_shows_attention_bar_and_empty_week(panel: str) -> None:
    status, body = _get(f"{panel}/")
    assert status == 200
    counts = _attention_counts(body)
    assert counts["Offene Anfragen prüfen"] == 0
    assert counts["Druckbestätigung fehlt"] == 0
    assert counts["Aufträge noch nicht wirksam"] == 0
    assert counts["Versandfreigabe blockiert"] == 0
    assert "Stornierte Aufträge prüfen" not in body  # no cancelled orders yet
    assert "Diese Woche" in body
    assert "keine wirksamen Aufträge diese Woche" in body
    assert "Offene Anfragen" in body
    assert "keine offenen Anfragen." in body
    assert "Aufträge mit nächstem Schritt" in body
    assert "keine offenen Schritte." in body


def test_attention_counts_reflect_new_inquiry_and_unconfirmed_order(panel: str) -> None:
    iid = _create_inquiry(panel)
    _status, body = _get(f"{panel}/")
    assert _attention_counts(body)["Offene Anfragen prüfen"] == 1

    oid = _convert(panel, iid)
    _status, body = _get(f"{panel}/")
    counts = _attention_counts(body)
    # Converting removes it from "Offene Anfragen prüfen" (now has an order)...
    assert counts["Offene Anfragen prüfen"] == 0
    # ...but the fresh order has no print confirmation, no effective version,
    # and is therefore also READY_TO_SEND-blocked.
    assert counts["Druckbestätigung fehlt"] == 1
    assert counts["Aufträge noch nicht wirksam"] == 1
    assert counts["Versandfreigabe blockiert"] == 1
    assert oid[:8] in body
    # "Aufträge mit nächstem Schritt" (§11 addendum) reuses the same
    # evaluation for the reason text, but the button is resolved from the
    # target version's own fields, not from reasons[0] directly: right
    # after convert, print isn't confirmed yet, so the correct next step is
    # "Küchendruck starten", never "Wirksam machen" (Core itself refuses that
    # for an unprinted version).
    assert "Aufträge mit nächstem Schritt" in body
    assert f'/order/{oid}">{oid[:8]}</a> — keine wirksame Auftragsversion' in body
    assert f'action="/order/{oid}/print-confirm"' in body
    assert f'action="/order/{oid}/effective"' not in body


def test_order_row_shows_first_blocker_reason(panel: str) -> None:
    iid = _create_inquiry(panel)
    _convert(panel, iid)
    _status, body = _get(f"{panel}/")
    assert (
        "keine wirksame Auftragsversion" in body
    )  # first reason right after convert, human label


def test_full_release_flow_clears_attention_counts(panel: str) -> None:
    iid = _create_inquiry(panel)
    oid = _convert(panel, iid)
    _status, body = _get(f"{panel}/order/{oid}")
    vid = body.split('name="order_version_id" value="')[1].split('"')[0]
    _post(f"{panel}/order/{oid}/print-confirm", {"order_version_id": vid})
    _simulate_kitchen_agent_ack(panel, vid)
    _post(f"{panel}/order/{oid}/effective", {"order_version_id": vid})
    _post(f"{panel}/order/{oid}/ready", {})
    _status, body = _get(f"{panel}/")
    counts = _attention_counts(body)
    assert counts["Druckbestätigung fehlt"] == 0
    assert counts["Aufträge noch nicht wirksam"] == 0
    assert counts["Versandfreigabe blockiert"] == 0
    assert "keine offenen Schritte." in body


def test_diese_woche_shows_only_effective_orders_in_current_iso_week(
    panel: str,
) -> None:
    today = office_api_views.berlin_today().isoformat()
    iid = _create_inquiry(panel, event_date=today, location_text="Kielort")
    oid = _convert(panel, iid)
    _status, body = _get(f"{panel}/order/{oid}")
    vid = body.split('name="order_version_id" value="')[1].split('"')[0]
    _post(f"{panel}/order/{oid}/print-confirm", {"order_version_id": vid})
    _simulate_kitchen_agent_ack(panel, vid)
    _post(f"{panel}/order/{oid}/effective", {"order_version_id": vid})

    _status, body = _get(f"{panel}/")
    assert "Kielort" in body
    assert "keine wirksamen Aufträge diese Woche" not in body

    # A different-week (default helper) order must not show up in the mini-week.
    other_iid = _create_inquiry(panel)  # default event_date=2026-10-01
    other_oid = _convert(panel, other_iid)
    _status, other_body = _get(f"{panel}/order/{other_oid}")
    other_vid = other_body.split('name="order_version_id" value="')[1].split('"')[0]
    _post(f"{panel}/order/{other_oid}/print-confirm", {"order_version_id": other_vid})
    _simulate_kitchen_agent_ack(panel, other_vid)
    _post(f"{panel}/order/{other_oid}/effective", {"order_version_id": other_vid})
    _status, body = _get(f"{panel}/")
    # Split on the unique heading id, not the text "Diese Woche" — that text
    # also appears in the sidebar nav link, which precedes the real content.
    # Diese Woche now sits above the Blocker section (§3 Arbeitszentrale), so
    # scope the check to that block only, not everything after it on the page.
    diese_woche_html = body.split('id="diese-woche"')[1].split(
        "<h2>Offene Anfragen</h2>"
    )[0]
    assert other_oid[:8] not in diese_woche_html


def test_full_list_tables_use_scan_first_columns_and_trailing_action(
    panel: str,
) -> None:
    """The full inquiry and order lists expose scan-first operational columns."""
    iid = _create_inquiry(panel)
    oid = _convert(panel, iid)

    _status, anfragen_body = _get(f"{panel}/anfragen")
    assert (
        "<th>Datum</th><th>Ort</th><th>Betreff</th><th>CRM-Stufe</th>"
        "<th>Verifizierung</th><th>Auftrag</th><th>ID</th>"
    ) in anfragen_body
    assert iid[:8] in anfragen_body

    _status, orders_body = _get(f"{panel}/orders")
    assert (
        "<th>Datum</th><th>Uhrzeit</th><th>Kunde</th>"
        "<th>Gäste</th><th>Nächster Schritt</th><th>Aktion</th>"
    ) in orders_body
    assert f'<a href="/order/{oid}">Öffnen</a></td></tr>' in orders_body


def test_search_filters_inquiries_and_orders(panel: str) -> None:
    """Search lives on /anfragen and /orders, not the Startseite (§11
    addendum: the dashboard is an action queue, not a searchable table)."""
    hamburg_iid = _create_inquiry(panel)  # default location "Hamburg"
    luebeck_iid = _create_inquiry(panel, location_text="Lübeck")

    _status, body = _get(f"{panel}/anfragen?q=L%C3%BCbeck")
    assert luebeck_iid[:8] in body
    assert hamburg_iid[:8] not in body

    _status, body = _get(f"{panel}/anfragen?q=nichts-passt-hier")
    assert luebeck_iid[:8] not in body and hamburg_iid[:8] not in body
    assert "keine" in body


def test_dashboard_has_no_search_box(panel: str) -> None:
    _status, body = _get(f"{panel}/")
    assert 'class="searchbox"' not in body


# -- Sidebar Rückruf badge --------------------------------------------------


def test_sidebar_has_no_badge_when_auerswald_not_configured(panel: str) -> None:
    _status, body = _get(f"{panel}/")
    assert '<span class="badge">' not in body


def test_sidebar_shows_badge_count_from_same_source_as_rueckrufliste() -> None:
    resolved: list = []
    hits: list = []
    stub = _make_auerswald_stub(resolved, hits)
    stub_thread = threading.Thread(target=stub.serve_forever, daemon=True)
    stub_thread.start()
    stub_host, stub_port = stub.server_address[:2]

    inquiry_repo = InMemoryInquiryRepository()
    order_repo = InMemoryOrderRepository()
    server = create_office_panel_server(
        inquiry_repo,
        order_repo,
        _PASSWORD,
        host="127.0.0.1",
        port=0,
        auerswald_url=f"http://{stub_host}:{stub_port}",
        auerswald_user="office",
        auerswald_password="secret",
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    base = f"http://{host}:{port}"
    try:
        # Badge visible from the Start page — not only inside /rueckruf itself.
        status, body = _get(f"{base}/")
        assert status == 200
        assert '<span class="badge">1</span>' in body
        assert len(hits) == 1  # exactly one fetch for this page load

        # /rueckruf reuses that fetch for both the list and its own badge —
        # still exactly one more request total, not two.
        status, body = _get(f"{base}/rueckruf")
        assert status == 200
        assert '<span class="badge">1</span>' in body
        assert len(hits) == 2  # one more request total for this page, not two
    finally:
        server.shutdown()
        server.server_close()
        stub.shutdown()
        stub.server_close()


def test_sidebar_badge_disappears_after_resolving_the_only_call() -> None:
    resolved: list = []
    stub = _make_auerswald_stub(resolved)
    stub_thread = threading.Thread(target=stub.serve_forever, daemon=True)
    stub_thread.start()
    stub_host, stub_port = stub.server_address[:2]

    inquiry_repo = InMemoryInquiryRepository()
    order_repo = InMemoryOrderRepository()
    server = create_office_panel_server(
        inquiry_repo,
        order_repo,
        _PASSWORD,
        host="127.0.0.1",
        port=0,
        auerswald_url=f"http://{stub_host}:{stub_port}",
        auerswald_user="office",
        auerswald_password="secret",
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    base = f"http://{host}:{port}"
    try:
        _status, body = _get(f"{base}/")
        assert '<span class="badge">1</span>' in body

        _post(f"{base}/rueckruf/resolve", {"call_id": _AUERSWALD_ITEMS[0]["call_id"]})
        # Stub now excludes the resolved call — badge must reflect that
        # immediately on the very next page load, no stale count.
        _status, body = _get(f"{base}/")
        assert '<span class="badge">' not in body
    finally:
        server.shutdown()
        server.server_close()
        stub.shutdown()
        stub.server_close()


# -- Action Dashboard (§11 addendum): Rückruf-nötig queue, degrade, kiosk --


def test_dashboard_shows_rueckruf_queue_from_auerswald_stub() -> None:
    resolved: list = []
    stub = _make_auerswald_stub(resolved)
    stub_thread = threading.Thread(target=stub.serve_forever, daemon=True)
    stub_thread.start()
    stub_host, stub_port = stub.server_address[:2]

    inquiry_repo = InMemoryInquiryRepository()
    order_repo = InMemoryOrderRepository()
    server = create_office_panel_server(
        inquiry_repo,
        order_repo,
        _PASSWORD,
        host="127.0.0.1",
        port=0,
        auerswald_url=f"http://{stub_host}:{stub_port}",
        auerswald_user="office",
        auerswald_password="secret",
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    base = f"http://{host}:{port}"
    try:
        _status, body = _get(f"{base}/")
        assert "Rückruf nötig" in body
        assert (
            "01234" in body
        )  # phone — the compact row is date/time/phone/contact only
        assert 'action="/rueckruf/resolve"' in body
        assert "/inquiry/new?phone=01234" in body  # "Anfrage erfassen" hint link
        assert '<a href="/rueckruf">Alle anzeigen</a>' in body
    finally:
        server.shutdown()
        server.server_close()
        stub.shutdown()
        stub.server_close()


def test_dashboard_survives_degraded_rueckruf_source() -> None:
    """Owner requirement: if the missed-call source is unreachable, the
    Startseite must still render — the Rückruf queue is simply omitted
    (same graceful-degrade convention as the sidebar badge), not an error
    page, and the rest of the dashboard keeps working."""
    inquiry_repo = InMemoryInquiryRepository()
    order_repo = InMemoryOrderRepository()
    server = create_office_panel_server(
        inquiry_repo,
        order_repo,
        _PASSWORD,
        host="127.0.0.1",
        port=0,
        auerswald_url="http://127.0.0.1:1",
        auerswald_user="u",
        auerswald_password="p",
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    base = f"http://{host}:{port}"
    try:
        status, body = _get(f"{base}/")
        assert status == 200
        assert "Rückruf nötig" not in body
        assert "Offene Anfragen" in body
        assert "Aufträge mit nächstem Schritt" in body
        assert "Was braucht Aufmerksamkeit?" in body
    finally:
        server.shutdown()
        server.server_close()


def test_dashboard_no_kiosk_link_when_kiosk_url_unset(panel: str) -> None:
    status, body = _get(f"{panel}/")
    assert status == 200
    assert "Vollständige Wochenübersicht" not in body


def test_dashboard_shows_kiosk_link_when_configured() -> None:
    inquiry_repo = InMemoryInquiryRepository()
    order_repo = InMemoryOrderRepository()
    server = create_office_panel_server(
        inquiry_repo,
        order_repo,
        _PASSWORD,
        host="127.0.0.1",
        port=0,
        kiosk_url="http://kiosk.local:8082",
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    base = f"http://{host}:{port}"
    try:
        status, body = _get(f"{base}/")
        assert status == 200
        assert 'href="http://kiosk.local:8082"' in body
        assert "Vollständige Wochenübersicht" in body
    finally:
        server.shutdown()
        server.server_close()


def test_inquiry_new_shows_phone_hint_but_writes_nothing_to_inquiry(panel: str) -> None:
    status, body = _get(f"{panel}/inquiry/new?phone=017112345")
    assert status == 200
    assert "Anruf von: 017112345" in body
    iid = _create_inquiry(panel)  # phone was never a form field -> unaffected
    _status, body = _get(f"{panel}/inquiry/{iid}")
    assert "017112345" not in body


def test_dashboard_queues_capped_at_five_with_alle_anzeigen_link(panel: str) -> None:
    for _ in range(7):
        _create_inquiry(panel)
    _status, body = _get(f"{panel}/")
    assert _attention_counts(body)["Offene Anfragen prüfen"] == 7
    assert "<button>Auftrag erstellen</button>" not in body
    assert "Angebot vorbereiten" in body
    assert '<a href="/anfragen">Alle anzeigen</a>' in body
    _status, full_body = _get(f"{panel}/anfragen")
    assert full_body.count("<tr>") == 8  # header row + all 7, not just top 5


# -- _next_step_action (§11 addendum §14, corrected version resolution) ----
# OfficePanel is "kept separate from the HTTP handler for testability"
# (class docstring) — tested directly here since the panel currently has no
# HTTP route that ever sets candidate_order_version_id (B6's
# set_candidate_order_version is service-layer only, unwired in the UI), so
# these scenarios aren't reachable through the black-box HTTP tests above.


def _panel_with_order():
    inquiry_repo = InMemoryInquiryRepository()
    order_repo = InMemoryOrderRepository()
    panel = OfficePanel(inquiry_repo, order_repo)
    inquiry = panel.inquiry_service.create_inquiry(
        event_date=date(2026, 10, 1),
        inquiry_source="phone",
        crm_stage="Neue Anfrage",
        customer_linkage={},
        time_window_text="mittags",
        location_text="Hamburg",
        guest_count_estimate=10,
        planning_mode="caterer_suggestion",
        call_verification_required=False,
        call_verification_status="not_required",
        contact_email="kunde@example.com",
        contact_phone="+49301234567",
    )
    order, v1 = seed_order(order_repo, inquiry)
    return panel, order, v1


def test_next_step_targets_latest_version_when_no_candidate_set() -> None:
    panel, order, v1 = _panel_with_order()
    action_html = panel._next_step_action(order, context=legacy_office_context())
    assert "Küchendruck starten" in action_html
    assert f'value="{v1.order_version_id}"' in action_html


def test_next_step_prefers_candidate_over_latest_version() -> None:
    panel, order, v1 = _panel_with_order()
    v2 = panel.order_service.create_relevant_order_change_version(
        order,
        event_date=date(2026, 10, 2),
        time_window_text="abends",
        location_text="Kiel",
        guest_count_estimate=12,
        planning_mode="caterer_suggestion",
    )
    panel.order_service.set_candidate_order_version(order.order_id, v1.order_version_id)
    order = panel._orders.get_order(order.order_id)
    action_html = panel._next_step_action(order, context=legacy_office_context())
    # Candidate is v1, not the higher version_number v2 -> v1 wins.
    assert f'value="{v1.order_version_id}"' in action_html
    assert v2.order_version_id not in action_html


def test_next_step_never_offers_effective_before_print_confirmed() -> None:
    """The real invariant this resolution exists to protect: Core itself
    refuses make_order_version_effective() for an unprinted version."""
    panel, order, v1 = _panel_with_order()
    action_html = panel._next_step_action(order, context=legacy_office_context())
    assert "print-confirm" in action_html
    assert "effective" not in action_html

    panel.core.confirm_kitchen_print(order.order_id, v1.order_version_id)
    order = panel._orders.get_order(order.order_id)
    action_html = panel._next_step_action(order, context=legacy_office_context())
    assert "Küchenzettel wurde gedruckt" in action_html
    assert f'action="/order/{order.order_id}/effective"' not in action_html


def test_next_step_falls_back_to_latest_when_candidate_is_foreign() -> None:
    """Defensive case: a candidate_order_version_id that doesn't resolve to
    any real version of this order must not crash the Startseite."""
    from dataclasses import replace

    panel, order, v1 = _panel_with_order()
    broken = replace(order, candidate_order_version_id="does-not-exist")
    action_html = panel._next_step_action(broken, context=legacy_office_context())
    assert f'value="{v1.order_version_id}"' in action_html


def test_next_step_empty_when_order_has_no_versions() -> None:
    from dataclasses import replace

    panel, order, _v1 = _panel_with_order()
    fake_order = replace(order, order_id="unknown-order-id")
    assert panel._next_step_action(fake_order, context=legacy_office_context()) == ""


# -- website_form Office UX (WEBSITE_FORM_INQUIRY_OFFICE_UX_PACK_V1) --------
# Source stays stored in Core, but Office Panel no longer renders source/Kanal.


def test_website_intake_to_office_verification_and_conversion_workflow() -> None:
    inquiry_repo = InMemoryInquiryRepository()
    order_repo = InMemoryOrderRepository()
    office = OfficePanel(inquiry_repo, order_repo)
    inquiry = intake_from_website_form(
        office.inquiry_service,
        {
            "event_date": date(2026, 10, 1),
            "location_text": "E2E Testort",
            "guest_count_estimate": 10,
            "company": "E2E TEST — KEIN KUNDE",
            "email": "e2e@example.test",
            "phone": "040 777 888",
            "submission_id": "office-workflow-e2e",
        },
    )

    queue = office.render_queue(None)
    from tests.helpers.office_panel_context import legacy_office_context

    detail = office.render_inquiry(inquiry.inquiry_id, context=legacy_office_context())
    assert inquiry.inquiry_id[:8] in queue
    assert detail is not None
    assert "<dt>Kanal</dt>" not in detail
    assert "Die Angaben stammen aus dem Website-Formular" not in detail
    assert "Telefonisch verifiziert" in detail
    assert office.progression.evaluate_inquiry_to_order_progression(inquiry).blocked
    assert order_repo.list_orders() == []

    office.inquiry_service.verify_customer_by_call(inquiry.inquiry_id)
    verified = inquiry_repo.get_by_id(inquiry.inquiry_id)
    assert verified is not None
    assert verified.call_verification_status == "verified"
    assert not office.progression.evaluate_inquiry_to_order_progression(
        verified
    ).blocked

    order, version = seed_order(order_repo, verified)
    assert order.source_inquiry_id == inquiry.inquiry_id
    assert version.version_number == 1
    assert [saved.order_id for saved in order_repo.list_orders()] == [order.order_id]


def test_list_hides_kanal_for_website_form_inquiries(panel: str) -> None:
    _iid = _create_website_form_inquiry(panel)
    _status, body = _get(f"{panel}/anfragen")
    assert "Website-Anfrage" not in body
    assert "website_form" not in body
    assert "Kanal" not in body


def test_list_shows_betreff_from_intake_subject(panel: str) -> None:
    _iid = _create_inquiry(panel, intake_subject="Firmenfeier Musterfirma")
    _status, body = _get(f"{panel}/anfragen")
    assert "Firmenfeier Musterfirma" in body


def test_list_betreff_truncated_around_40_chars(panel: str) -> None:
    long_subject = "X" * 60
    _iid = _create_inquiry(panel, intake_subject=long_subject)
    _status, body = _get(f"{panel}/anfragen")
    assert ("X" * 40 + "…") in body
    assert long_subject not in body


def test_list_empty_betreff_renders_dash(panel: str) -> None:
    _iid = _create_inquiry(panel)
    _status, body = _get(f"{panel}/anfragen")
    assert "<td>–</td>" in body


def test_list_hides_kanal_for_office_created_inquiries(panel: str) -> None:
    _iid = _create_inquiry(panel)
    _status, body = _get(f"{panel}/anfragen")
    assert "Telefon (Büro)" not in body
    assert "phone_by_office" not in body


def test_list_pending_required_verification_uses_blocked_class(panel: str) -> None:
    _iid = _create_inquiry(panel, call_verification_required="1")
    _status, body = _get(f"{panel}/anfragen")
    assert '<span class="blocked">Rückrufprüfung ausstehend</span>' in body


def test_list_verified_or_not_required_has_no_blocked_class(panel: str) -> None:
    _iid = _create_inquiry(panel)  # call_verification_required not set → not_required
    _status, body = _get(f"{panel}/anfragen")
    assert '<span class="blocked">' not in body


def test_search_does_not_find_by_inquiry_source(panel: str) -> None:
    _iid = _create_website_form_inquiry(panel)
    _status, body = _get(f"{panel}/anfragen?q=website_form")
    assert _iid[:8] not in body


def test_search_finds_by_intake_subject(panel: str) -> None:
    iid = _create_inquiry(panel, intake_subject="EinzigartigerSuchbegriff")
    _status, body = _get(f"{panel}/anfragen?q=EinzigartigerSuchbegriff")
    assert iid[:8] in body


def test_detail_hides_source_row_for_website_form(panel: str) -> None:
    iid = _create_website_form_inquiry(panel)
    _status, body = _get(f"{panel}/inquiry/{iid}")
    assert "<dt>Kanal</dt>" not in body


def test_detail_hides_website_form_banner(panel: str) -> None:
    iid = _create_website_form_inquiry(panel)
    _status, body = _get(f"{panel}/inquiry/{iid}")
    assert "Die Angaben stammen aus dem Website-Formular" not in body
    assert "proposal-banner" not in body


def test_detail_banner_absent_for_non_website_source(panel: str) -> None:
    iid = _create_inquiry(panel)
    _status, body = _get(f"{panel}/inquiry/{iid}")
    assert "noch kein Auftrag" not in body


def test_detail_intake_message_remains_escaped(panel: str) -> None:
    from dataclasses import replace

    iid = _create_website_form_inquiry(panel)
    inquiries, _orders, _snapshots = _PANEL_REPOS[panel]
    inquiry = inquiries.get_by_id(iid)
    assert inquiry is not None
    inquiries.update(
        replace(inquiry, intake_message="<script>alert(1)</script> & special")
    )
    _status, body = _get(f"{panel}/inquiry/{iid}")
    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;" in body


def test_verification_button_text_unchanged_for_website_form(panel: str) -> None:
    iid = _create_website_form_inquiry(panel)
    _status, body = _get(f"{panel}/inquiry/{iid}")
    assert "Telefonisch verifiziert" in body
    assert "Rückruf erledigt" not in body


def test_viewing_list_and_detail_creates_no_order_or_orderversion() -> None:
    inquiry_repo = InMemoryInquiryRepository()
    order_repo = InMemoryOrderRepository()
    server = create_office_panel_server(
        inquiry_repo, order_repo, _PASSWORD, host="127.0.0.1", port=0
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    base = f"http://{host}:{port}"
    try:
        office = OfficePanel(inquiry_repo, order_repo)
        iid = intake_from_website_form(
            office.inquiry_service,
            {
                "event_date": date(2026, 10, 1),
                "location_text": "Hamburg",
                "guest_count_estimate": 25,
                "company": "Website Anfrage GmbH",
                "email": "kunde@example.com",
                "phone": "040 123456",
                "submission_id": "web-42",
            },
        ).inquiry_id
        _get(f"{base}/anfragen")
        _get(f"{base}/inquiry/{iid}")
        assert order_repo.list_orders() == []
        assert order_repo._versions == {}  # noqa: SLF001
    finally:
        server.shutdown()
        server.server_close()


def test_conversion_still_blocked_for_unverified_website_form_inquiry(
    panel: str,
) -> None:
    iid = _create_website_form_inquiry(panel)
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(f"{panel}/inquiry/{iid}/convert", {})
    assert exc.value.code == 400
