"""Unit tests — office panel (OFFICE_PANEL_EXECUTION_PACK_V1 §8). Live-socket, basic auth."""

from __future__ import annotations

from tests.helpers.commercial_snapshot_seed import seed_commercial_snapshot
from tests.helpers.order_seed import seed_order

import base64
import html
import json
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from catering_system.intake.website_form_adapter import intake_from_website_form
from catering_system.repositories.in_memory_inquiry_repository import (
    InMemoryInquiryRepository,
)
from catering_system.repositories.in_memory_order_commercial_snapshot_repository import (
    InMemoryOrderCommercialSnapshotRepository,
)
from catering_system.repositories.in_memory_order_repository import (
    InMemoryOrderRepository,
)
from catering_system.ui import office_api_views
from catering_system.ui.office_panel import (
    OfficePanel,
    create_office_panel_server,
    parse_proposal_payload,
    render_proposal_preview_form,
)
from catering_system.ui.office_panel_http import csrf_token_for_password
from catering_system.ui.office_panel_shell import OFFICE_PANEL_STYLE
from catering_system.ui.office_panel_views import _page
from tests.helpers.office_panel_context import legacy_office_context

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


@pytest.fixture()
def panel():
    inquiry_repo = InMemoryInquiryRepository()
    order_repo = InMemoryOrderRepository()
    snapshots = InMemoryOrderCommercialSnapshotRepository()
    server = create_office_panel_server(
        inquiry_repo,
        order_repo,
        _PASSWORD,
        host="127.0.0.1",
        port=0,
        commercial_snapshot_repo=snapshots,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    base = f"http://{host}:{port}"
    _PANEL_REPOS[base] = (inquiry_repo, order_repo, snapshots)
    yield base
    _PANEL_REPOS.pop(base, None)
    server.shutdown()
    server.server_close()


@pytest.fixture()
def premium_panel():
    inquiry_repo = InMemoryInquiryRepository()
    order_repo = InMemoryOrderRepository()
    snapshots = InMemoryOrderCommercialSnapshotRepository()
    server = create_office_panel_server(
        inquiry_repo,
        order_repo,
        _PASSWORD,
        host="127.0.0.1",
        port=0,
        commercial_snapshot_repo=snapshots,
        ui_version="v2",
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    base = f"http://{host}:{port}"
    _PANEL_REPOS[base] = (inquiry_repo, order_repo, snapshots)
    yield base
    _PANEL_REPOS.pop(base, None)
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
        "inquiry_source": "phone",
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


def test_page_context_badge_does_not_leak_between_renders() -> None:
    with_badge = render_proposal_preview_form(
        context=legacy_office_context(rueckruf_count=3)
    )
    without_badge = render_proposal_preview_form(context=legacy_office_context())

    assert '<span class="badge">3</span>' in with_badge
    assert '<span class="badge">' not in without_badge


def test_v2_shell_uses_explicit_active_section_and_semantic_landmarks() -> None:
    body = _page(
        "Anfragen",
        "<p>Inhalt</p>",
        active_section="orders",
        context=legacy_office_context(),
    )

    assert '<nav class="office-nav" aria-label="Office Panel">' in body
    assert '<main class="office-workspace">' in body
    assert '<a class="office-nav-link" href="/auftraege" aria-current="page">' in body
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
        'href="/auftraege"',
        'href="/#diese-woche"',
        'href="/rueckruf"',
        'href="/proposal-preview"',
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
        "office-i-import",
        "office-i-users",
        "office-i-printer",
        "office-i-check",
    }
    assert all(body.count(f'<symbol id="{symbol}"') == 1 for symbol in symbols)


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
        ("/auftraege", "/auftraege"),
        ("/inquiry/new", "/anfragen"),
        ("/rueckruf", "/rueckruf"),
        ("/proposal-preview", "/proposal-preview"),
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
        '<a class="office-nav-link" href="/auftraege" aria-current="page">'
        in order_body
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

    payload = json.dumps(
        {
            "schema_version": "proposal_payload_v1",
            "source": "fingerfood-configurator",
            "title": "CSRF preview",
            "event_date": "2026-10-01",
            "guest_count": 10,
            "selected_items": [],
        }
    )
    _status, _url, preview_page = _post(
        f"{panel}/proposal-preview", {"payload_json": payload}
    )
    _assert_all_post_forms_have_csrf(preview_page)


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
        assert "script-src" not in csp
        assert response.headers["Referrer-Policy"] == "no-referrer"
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"


def test_office_panel_rejects_oversized_form_body(panel: str) -> None:
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(f"{panel}/proposal-preview", {"payload_json": "x" * (300 * 1024)})
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
    assert "Druck bestätigen" in initial

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
    assert "Druck bestätigen" in saved


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


def test_new_inquiry_form_shows_office_safe_source_dropdown_and_warning(
    panel: str,
) -> None:
    status, body = _get(f"{panel}/inquiry/new")
    assert status == 200
    assert "Intake-Kontext — keine Auftrags-/Küchenfreigabe." in body
    kanal_select = re.search(r'name="inquiry_source">(.*?)</select>', body, re.DOTALL)
    assert kanal_select is not None
    options = re.findall(r'<option value="([^"]+)">', kanal_select.group(1))
    assert options == [
        "manual",
        "phone_by_office",
        "email",
        "website_form",
        "configurator",
    ]
    # legacy/adapter-only/future sources deliberately not office-offered
    for hidden in ("phone", "wix_form", "missed_call", "ai_telefonist"):
        assert f'value="{hidden}"' not in body


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
    _status, body = _get(f"{panel}/order/{oid}")
    assert f'action="/order/{oid}/print-confirm"' not in body
    assert f'action="/order/{oid}/effective"' in body
    assert "Wirksam machen" in body


def test_full_release_flow(panel: str) -> None:
    iid = _create_inquiry(panel)
    oid = _convert(panel, iid)
    _status, body = _get(f"{panel}/order/{oid}")
    vid = body.split('name="order_version_id" value="')[1].split('"')[0]
    _post(f"{panel}/order/{oid}/print-confirm", {"order_version_id": vid})
    _status, _url, body = _post(
        f"{panel}/order/{oid}/effective", {"order_version_id": vid}
    )
    assert "wirksam" in body
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
    assert "Küchenzettel" in sheet and "Hamburg" in sheet and "MENÜ" in sheet


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
    order_id = _convert(premium_panel, inquiry_id)

    _status, initial = _get(f"{premium_panel}/order/{order_id}")
    version_id = re.search(r'name="order_version_id" value="([^"]+)"', initial).group(1)

    assert "order-hero" in initial
    assert "<h1>Auftrag für den 01.10.2026</h1>" in initial
    assert "Küchenzettel für Stand 1 drucken" in initial
    assert f'action="/order/{order_id}/print-confirm"' in initial
    assert f'action="/order/{order_id}/effective"' not in initial
    assert "Noch kein Stand ist als aktueller Küchenstand festgelegt." in initial
    assert "READY_TO_SEND" not in initial

    _post(
        f"{premium_panel}/order/{order_id}/print-confirm",
        {"order_version_id": version_id},
    )
    _status, printed = _get(f"{premium_panel}/order/{order_id}")

    assert "Stand 1 als Küchenstand festlegen" in printed
    assert f'action="/order/{order_id}/print-confirm"' not in printed
    assert f'action="/order/{order_id}/effective"' in printed

    _post(
        f"{premium_panel}/order/{order_id}/effective",
        {"order_version_id": version_id},
    )
    _status, effective = _get(f"{premium_panel}/order/{order_id}")

    assert "Vorbereitung vollständig" in effective
    assert "Die Versandfreigabe ist erfüllt." in effective
    assert f'action="/order/{order_id}/effective"' not in effective
    assert f'action="/order/{order_id}/ready"' in effective

    visible = html.unescape(re.sub(r"<[^>]+>", " ", effective))
    assert order_id[:8] not in visible
    assert inquiry_id[:8] not in visible
    assert "caterer_suggestion" not in visible
    assert "READY_TO_SEND" not in visible


def test_v2_order_detail_prefers_new_candidate_over_ready_old_stand(
    premium_panel: str,
) -> None:
    inquiry_id = _create_inquiry(premium_panel)
    order_id = _convert(premium_panel, inquiry_id)
    _status, initial = _get(f"{premium_panel}/order/{order_id}")
    version_id = re.search(r'name="order_version_id" value="([^"]+)"', initial).group(1)
    _post(
        f"{premium_panel}/order/{order_id}/print-confirm",
        {"order_version_id": version_id},
    )
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

    assert "<h1>Auftrag für den 03.10.2026</h1>" in body
    assert "Küchenzettel für Stand 2 drucken" in body
    assert "Hamburg-Altona" in body
    assert "Auswahl durch den Kunden" in body
    assert "Nächster Stand" in body
    assert "Eine Änderung wartet noch auf Küchendruck" in body
    assert "Aktueller Küchenstand" in body
    assert "Aktueller Bearbeitungsstand" in body


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
    assert "Zahlungseingang prüfen" in body
    assert "Reminder-Status" in body
    assert "RE-UI4-1" in body
    assert f'action="/order/{order_id}/payment-reminder"' in body
    assert "Küchenzettel für Stand 1 drucken" in body

    _post(f"{premium_panel}/order/{order_id}/cancel", {})
    _status, cancelled = _get(f"{premium_panel}/order/{order_id}")

    assert "STORNIERT" in cancelled
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
    ):
        assert f'action="/order/{order_id}/{action}"' not in cancelled


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
    # "Druck bestätigen", never "Wirksam machen" (Core itself refuses that
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


def test_queue_tables_put_id_last_not_first(panel: str) -> None:
    """OFFICE_PANEL_NAVIGATION_RETHINK_PACK_V1 §4: ID demoted to a trailing
    link column so office staff scan Datum/Ort/Status first. Full tables
    live on /anfragen and /auftraege (§11 addendum), not the Startseite."""
    iid = _create_inquiry(panel)
    oid = _convert(panel, iid)
    _status, anfragen_body = _get(f"{panel}/anfragen")
    assert (
        "<th>Datum</th><th>Ort</th><th>Kanal</th><th>Betreff</th>"
        "<th>CRM-Stufe</th><th>Verifizierung</th>"
        "<th>Auftrag</th><th>ID</th>"
    ) in anfragen_body
    assert iid[:8] in anfragen_body

    _status, auftraege_body = _get(f"{panel}/auftraege")
    assert (
        "<th>Freigabe</th><th>Blocker</th><th>Anfrage</th><th>Bestätigt</th><th>ID</th>"
    ) in auftraege_body
    assert "noch nicht bestätigt" in auftraege_body
    assert (
        f'<a href="/order/{oid}">{oid[:8]}</a></td></tr>' in auftraege_body
    )  # ID cell is last


def test_search_filters_inquiries_and_orders(panel: str) -> None:
    """Search lives on /anfragen and /auftraege, not the Startseite (§11
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
    assert "Druck bestätigen" in action_html
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
    assert "Wirksam machen" in action_html
    assert f'action="/order/{order.order_id}/effective"' in action_html


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


# -- proposal preview (CONFIGURATOR_OFFICE_MANUAL_HANDOFF_PACK_V1) --------
# Read-only import preview for proposal_payload_v1: parse and render only.
# Nothing here may create an Inquiry, Order, or OrderVersion.

_VALID_PROPOSAL: dict = {
    "schema_version": "proposal_payload_v1",
    "source": "fingerfood-configurator",
    "proposal_id": "local-42",
    "title": "Angebot Sommerfest",
    "event_date": "2026-09-12",
    "guest_count": 30,
    "selected_items": [
        {
            "name": "Mini Wraps",
            "quantity": 30,
            "unit_price": 2.9,
            "total_price": 87.0,
            "notes": "vegetarisch",
        }
    ],
    "calculated_total_net": 87.0,
    "calculated_total_gross": 103.53,
    "notes": "Freitext aus Angebotsphase",
}


def _proposal(remove: tuple[str, ...] = (), **overrides: object) -> str:
    data = {k: v for k, v in _VALID_PROPOSAL.items() if k not in remove}
    data.update(overrides)
    return json.dumps(data)


# parser --


def test_parse_proposal_valid() -> None:
    payload = parse_proposal_payload(_proposal())
    assert payload["title"] == "Angebot Sommerfest"
    assert payload["selected_items"][0]["name"] == "Mini Wraps"


def test_parse_proposal_invalid_json() -> None:
    with pytest.raises(ValueError) as exc:
        parse_proposal_payload("{not json")
    message = str(exc.value)
    # human-friendly hint first, technical detail preserved after it
    assert "Ungültiges JSON" in message
    assert ".json-Datei" in message
    assert "nicht den Dateinamen" in message
    assert "Technisches Detail:" in message


def test_parse_proposal_not_an_object() -> None:
    with pytest.raises(ValueError) as exc:
        parse_proposal_payload('["a", "b"]')
    message = str(exc.value)
    assert "JSON-Objekt" in message
    assert ".json-Datei" in message


def test_parse_proposal_schema_version_missing_or_wrong() -> None:
    with pytest.raises(ValueError, match="schema_version"):
        parse_proposal_payload(_proposal(remove=("schema_version",)))
    with pytest.raises(ValueError, match="schema_version"):
        parse_proposal_payload(_proposal(schema_version="proposal_payload_v2"))


def test_parse_proposal_source_missing_or_wrong() -> None:
    with pytest.raises(ValueError, match="source"):
        parse_proposal_payload(_proposal(remove=("source",)))
    with pytest.raises(ValueError, match="source"):
        parse_proposal_payload(_proposal(source="somewhere-else"))


def test_parse_proposal_title_missing_or_empty() -> None:
    with pytest.raises(ValueError, match="title"):
        parse_proposal_payload(_proposal(remove=("title",)))
    with pytest.raises(ValueError, match="title"):
        parse_proposal_payload(_proposal(title="   "))


def test_parse_proposal_event_date_missing_or_invalid() -> None:
    with pytest.raises(ValueError, match="event_date"):
        parse_proposal_payload(_proposal(remove=("event_date",)))
    with pytest.raises(ValueError, match="event_date"):
        parse_proposal_payload(_proposal(event_date="12.09.2026"))


def test_parse_proposal_guest_count_missing_or_invalid() -> None:
    with pytest.raises(ValueError, match="guest_count"):
        parse_proposal_payload(_proposal(remove=("guest_count",)))
    with pytest.raises(ValueError, match="guest_count"):
        parse_proposal_payload(_proposal(guest_count="30"))
    # >= 1: no evidence anywhere in domain/services that 0 guests is a
    # supported value, so the preview refuses it.
    with pytest.raises(ValueError, match="guest_count"):
        parse_proposal_payload(_proposal(guest_count=0))
    # bool is an int subclass and must not slip through.
    with pytest.raises(ValueError, match="guest_count"):
        parse_proposal_payload(_proposal(guest_count=True))


def test_parse_proposal_selected_items_missing_or_invalid() -> None:
    with pytest.raises(ValueError, match="selected_items"):
        parse_proposal_payload(_proposal(remove=("selected_items",)))
    with pytest.raises(ValueError, match="selected_items"):
        parse_proposal_payload(_proposal(selected_items="Mini Wraps"))
    with pytest.raises(ValueError, match=r"selected_items\[1\]"):
        parse_proposal_payload(_proposal(selected_items=["just a string"]))
    with pytest.raises(ValueError, match="name"):
        parse_proposal_payload(_proposal(selected_items=[{"quantity": 5}]))
    with pytest.raises(ValueError, match="name"):
        parse_proposal_payload(_proposal(selected_items=[{"name": "  "}]))


def test_parse_proposal_optional_fields_absent_ok() -> None:
    raw = _proposal(
        remove=(
            "proposal_id",
            "calculated_total_net",
            "calculated_total_gross",
            "notes",
        ),
        selected_items=[{"name": "Mini Wraps"}],
    )
    payload = parse_proposal_payload(raw)
    assert payload["guest_count"] == 30
    assert payload["selected_items"] == [{"name": "Mini Wraps"}]


# HTTP --


def test_proposal_preview_form_renders(panel: str) -> None:
    status, body = _get(f"{panel}/proposal-preview")
    assert status == 200
    assert "payload_json" in body and "<textarea" in body
    assert "keine Core-Daten wurden erstellt oder geändert" in body
    assert "not operational truth" in body
    # office-user instructions (UX fix after the first live test)
    assert "So funktioniert der Büro-Import" in body
    assert "Export fürs Büro (JSON)" in body
    assert "nur den Inhalt der .json-Datei" in body


def test_proposal_preview_post_valid_renders_preview(panel: str) -> None:
    status, _url, body = _post(
        f"{panel}/proposal-preview", {"payload_json": _proposal()}
    )
    assert status == 200
    assert "fingerfood-configurator" in body
    assert "Angebot Sommerfest" in body
    assert "2026-09-12" in body
    assert "Mini Wraps" in body
    assert "2.9" in body and "87.0" in body and "103.53" in body
    assert "Freitext aus Angebotsphase" in body
    # explicit not-truth marking on the preview itself
    assert "proposal/import preview" in body
    assert "keine Core-Daten wurden erstellt oder geändert" in body
    assert "not operational truth" in body


def test_proposal_preview_post_invalid_json_is_400(panel: str) -> None:
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(f"{panel}/proposal-preview", {"payload_json": "{not json"})
    assert exc.value.code == 400
    body = exc.value.read().decode("utf-8")
    assert "Ungültiges JSON" in body
    # human-friendly hint for the office user, not just the parser detail
    assert ".json-Datei" in body
    assert "nicht den Dateinamen" in body


def test_proposal_preview_post_wrong_schema_version_is_400(panel: str) -> None:
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(
            f"{panel}/proposal-preview",
            {"payload_json": _proposal(schema_version="something_else")},
        )
    assert exc.value.code == 400
    assert "schema_version" in exc.value.read().decode("utf-8")


def test_proposal_preview_creates_nothing_in_core() -> None:
    """The boundary test: a successful preview POST leaves Core repositories
    completely empty — no Inquiry, no Order, no OrderVersion."""
    inquiry_repo = InMemoryInquiryRepository()
    order_repo = InMemoryOrderRepository()
    server = create_office_panel_server(
        inquiry_repo, order_repo, _PASSWORD, host="127.0.0.1", port=0
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        status, _url, _body = _post(
            f"http://{host}:{port}/proposal-preview", {"payload_json": _proposal()}
        )
        assert status == 200
        assert inquiry_repo.list_all() == []
        assert order_repo.list_orders() == []
    finally:
        server.shutdown()
        server.server_close()


# -- "Anfrage aus Vorschau vorbereiten" (PROPOSAL_PREVIEW_MANUAL_INQUIRY_
# PACK_V1 §4, narrowed): GET-only link from a rendered preview into the
# existing /inquiry/new form, carrying only event_date + guest_count_estimate.


def _prepare_form_hidden_payload(body: str) -> dict:
    """Extract and JSON-decode the prepare form's hidden payload_json field."""
    assert 'action="/proposal-preview/prepare"' in body
    raw = body.split('name="payload_json" value="')[1].split('">')[0]
    return json.loads(html.unescape(raw))


def test_proposal_preview_contains_prepare_form_with_full_payload(panel: str) -> None:
    """PROPOSAL_PREVIEW_INTAKE_MAPPING_IMPLEMENTATION_PACK_V1 §3/§6: the
    prepare button is now a POST form (not a GET link with two safe hints),
    carrying the already-validated payload re-serialized, unmodified — the
    mapping/stripping of prices happens at prepare time (§5/§6), not here."""
    _status, _url, body = _post(
        f"{panel}/proposal-preview", {"payload_json": _proposal()}
    )
    assert "Anfrage aus Vorschau vorbereiten" in body
    hidden = _prepare_form_hidden_payload(body)
    assert hidden["title"] == "Angebot Sommerfest"
    assert hidden["event_date"] == "2026-09-12"
    assert hidden["guest_count"] == 30
    assert hidden["selected_items"][0]["name"] == "Mini Wraps"
    assert hidden["proposal_id"] == "local-42"


def test_inquiry_form_prefills_from_query(panel: str) -> None:
    status, body = _get(
        f"{panel}/inquiry/new?event_date=2026-09-12&guest_count_estimate=30"
    )
    assert status == 200
    assert 'name="event_date" value="2026-09-12"' in body
    assert 'name="guest_count_estimate" inputmode="numeric" value="30"' in body
    # still the existing form with its explicit submit — no new write control
    assert "Anfrage anlegen" in body


def test_inquiry_form_without_query_renders_empty_prefill(panel: str) -> None:
    status, body = _get(f"{panel}/inquiry/new")
    assert status == 200
    assert 'name="event_date" value=""' in body
    assert 'name="guest_count_estimate" inputmode="numeric" value=""' in body


def test_prepare_link_get_creates_nothing_in_core() -> None:
    """Following the prepare link (GET with hints) must not create anything."""
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
    """Query hints are prefill only: the office-edited form values are what
    create the Inquiry, and no Order/OrderVersion appears anywhere."""
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
        # office saw hints 2026-09-12 / 30, but edited both before submitting
        _status, _url, body = _post(
            f"{base}/inquiry/new",
            {
                "event_date": "2026-10-05",
                "inquiry_source": "manual",
                "time_window_text": "",
                "location_text": "",
                "guest_count_estimate": "25",
                "planning_mode": "caterer_suggestion",
            },
        )
        inquiries = inquiry_repo.list_all()
        assert len(inquiries) == 1
        assert inquiries[0].event_date.isoformat() == "2026-10-05"
        assert inquiries[0].guest_count_estimate == 25
        assert order_repo.list_orders() == []
    finally:
        server.shutdown()
        server.server_close()


# -- POST /proposal-preview/prepare (PROPOSAL_PREVIEW_INTAKE_MAPPING_
# IMPLEMENTATION_PACK_V1): read-only mapping step between the preview and
# the existing /inquiry/new form. Writes nothing; the only write anywhere
# in this flow stays the pre-existing explicit POST /inquiry/new submit.


def _prepare(base: str, proposal_json: str) -> tuple[int, str]:
    status, _url, body = _post(
        f"{base}/proposal-preview/prepare", {"payload_json": proposal_json}
    )
    return status, body


def test_prepare_renders_inquiry_form_with_mapped_intake_fields(panel: str) -> None:
    status, body = _prepare(panel, _proposal())
    assert status == 200
    assert "Anfrage anlegen" in body  # still the existing, unmodified form
    assert 'name="inquiry_source"' in body
    assert '<option value="configurator" selected>' in body
    assert 'name="event_date" value="2026-09-12"' in body
    assert 'name="guest_count_estimate" inputmode="numeric" value="30"' in body
    assert 'name="intake_subject" value="Angebot Sommerfest"' in body
    assert ">Freitext aus Angebotsphase</textarea>" in body  # intake_message from notes
    assert ">Mini Wraps × 30</textarea>" in body  # intake_summary
    assert 'name="intake_external_ref" value="local-42"' in body  # from proposal_id


def test_prepare_intake_summary_falls_back_to_name_without_quantity(panel: str) -> None:
    proposal = _proposal(
        selected_items=[{"name": "Servietten"}, {"name": "Mini Wraps", "quantity": 10}]
    )
    _status, body = _prepare(panel, proposal)
    assert ">Servietten\nMini Wraps × 10</textarea>" in body


def test_prepare_response_contains_no_price_figures(panel: str) -> None:
    _status, body = _prepare(panel, _proposal())
    for forbidden in ("€", "2.9", "87.0", "103.53", "unit_price", "total_price"):
        assert forbidden not in body


def test_prepare_missing_notes_and_proposal_id_prefill_empty(panel: str) -> None:
    proposal = _proposal(remove=("notes", "proposal_id"))
    _status, body = _prepare(panel, proposal)
    assert 'name="intake_external_ref" value=""' in body
    assert '<textarea name="intake_message" rows="4"></textarea>' in body


def test_prepare_invalid_json_is_400(panel: str) -> None:
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(f"{panel}/proposal-preview/prepare", {"payload_json": "{not json"})
    assert exc.value.code == 400
    body = exc.value.read().decode("utf-8")
    assert "Ungültiges JSON" in body


def test_prepare_wrong_schema_version_is_400(panel: str) -> None:
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(
            f"{panel}/proposal-preview/prepare",
            {"payload_json": _proposal(schema_version="something_else")},
        )
    assert exc.value.code == 400


def test_prepare_handles_long_multiline_notes_and_many_items(panel: str) -> None:
    """Regression guard for the transport decision (pack §3): a long,
    multi-paragraph note plus many selected_items must round-trip correctly
    through the POST body — this would be exactly the case a GET query
    string handles awkwardly or truncates."""
    long_note = "Kunde ruft zurück.\n\n" + ("Sehr ausführlicher Wunschtext. " * 60)
    many_items = [{"name": f"Position {i}", "quantity": i} for i in range(1, 21)]
    proposal = _proposal(notes=long_note, selected_items=many_items)
    status, body = _prepare(panel, proposal)
    assert status == 200
    assert "Sehr ausführlicher Wunschtext." in body
    assert "Position 1 × 1" in body
    assert "Position 20 × 20" in body


def test_prepare_creates_nothing_in_core() -> None:
    inquiry_repo = InMemoryInquiryRepository()
    order_repo = InMemoryOrderRepository()
    server = create_office_panel_server(
        inquiry_repo, order_repo, _PASSWORD, host="127.0.0.1", port=0
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        status, _body = _prepare(f"http://{host}:{port}", _proposal())
        assert status == 200
        assert inquiry_repo.list_all() == []
        assert order_repo.list_orders() == []
        assert order_repo._versions == {}  # noqa: SLF001
    finally:
        server.shutdown()
        server.server_close()


def test_explicit_submit_after_prepare_uses_edited_values_not_proposal_defaults() -> (
    None
):
    """The office sees prepare's prefilled values (from the proposal) but
    edits them before submitting — the edited values must win, exactly like
    the existing query-hint flow's test_manual_submit_wins_over_query_hints."""
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
        status, _body = _prepare(base, _proposal())
        assert status == 200
        _status, _url, body = _post(
            f"{base}/inquiry/new",
            {
                "event_date": "2026-10-05",
                "inquiry_source": "manual",
                "time_window_text": "",
                "location_text": "",
                "guest_count_estimate": "25",
                "planning_mode": "caterer_suggestion",
                "intake_subject": "Vom Büro überarbeiteter Betreff",
                "intake_message": "",
                "intake_summary": "",
                "intake_external_ref": "",
            },
        )
        inquiries = inquiry_repo.list_all()
        assert len(inquiries) == 1
        assert inquiries[0].event_date.isoformat() == "2026-10-05"
        assert inquiries[0].guest_count_estimate == 25
        assert inquiries[0].inquiry_source == "manual"
        assert inquiries[0].intake_subject == "Vom Büro überarbeiteter Betreff"
        assert order_repo.list_orders() == []
    finally:
        server.shutdown()
        server.server_close()


def test_prepare_then_submit_then_convert_does_not_leak_intake_into_order(
    panel: str,
) -> None:
    """Full flow: prepare -> explicit submit -> convert. selected_items never
    become OrderVersion.items; no price ever reaches Core."""
    _status, prepare_body = _prepare(panel, _proposal())
    assert "Mini Wraps × 30" in prepare_body

    _status, url, _body = _post(
        f"{panel}/inquiry/new",
        {
            "event_date": "2026-09-12",
            "inquiry_source": "configurator",
            "time_window_text": "",
            "location_text": "",
            "guest_count_estimate": "30",
            "planning_mode": "caterer_suggestion",
            "contact_email": "kunde@example.com",
            "contact_phone": "030 1234567",
            "intake_subject": "Angebot Sommerfest",
            "intake_message": "Freitext aus Angebotsphase",
            "intake_summary": "Mini Wraps × 30",
            "intake_external_ref": "local-42",
        },
    )
    iid = url.rsplit("/", 1)[-1]
    oid = _convert(panel, iid)
    status, order_body = _get(f"{panel}/order/{oid}")
    assert status == 200
    assert "Mini Wraps" not in order_body
    assert "2.9" not in order_body and "87.0" not in order_body

    from dataclasses import fields

    from catering_system.domain.order import Order, OrderVersion

    assert not any(f.name.startswith("intake_") for f in fields(Order))
    assert not any(f.name.startswith("intake_") for f in fields(OrderVersion))


def test_prepare_then_submit_does_not_change_wochenuebersicht() -> None:
    from catering_system.services.wochenuebersicht_service import (
        WochenuebersichtService,
    )

    inquiry_repo = InMemoryInquiryRepository()
    order_repo = InMemoryOrderRepository()
    server = create_office_panel_server(
        inquiry_repo, order_repo, _PASSWORD, host="127.0.0.1", port=0
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    base = f"http://{host}:{port}"
    week = WochenuebersichtService(order_repo)
    before = week.get_week_overview(2026, 37)
    try:
        _prepare(base, _proposal())
        _post(
            f"{base}/inquiry/new",
            {
                "event_date": "2026-09-12",
                "inquiry_source": "configurator",
                "time_window_text": "",
                "location_text": "",
                "guest_count_estimate": "30",
                "planning_mode": "caterer_suggestion",
                "contact_email": "kunde@example.com",
                "contact_phone": "030 1234567",
                "intake_subject": "Angebot Sommerfest",
            },
        )
        after = week.get_week_overview(2026, 37)
        assert after == before
    finally:
        server.shutdown()
        server.server_close()


# -- website_form Office UX (WEBSITE_FORM_INQUIRY_OFFICE_UX_PACK_V1) --------
# Kanal/Betreff list columns, shared source label helper, website_form-only
# detail banner, extended search. No verification/action-flow changes.


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
    assert "Website-Anfrage" in detail
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


def test_list_shows_website_form_kanal_label(panel: str) -> None:
    _iid = _create_inquiry(panel, inquiry_source="website_form")
    _status, body = _get(f"{panel}/anfragen")
    assert "Website-Anfrage" in body
    assert "website_form" not in body  # raw enum never shown, label only


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


def test_source_label_helper_covers_non_website_source(panel: str) -> None:
    """The label dict isn't a one-off for website_form — confirms it works
    generically, using manual (an office-dropdown-visible source) as the
    non-website case."""
    _iid = _create_inquiry(panel, inquiry_source="manual")
    _status, body = _get(f"{panel}/anfragen")
    assert "Manuell erfasst" in body


def test_list_pending_required_verification_uses_blocked_class(panel: str) -> None:
    _iid = _create_inquiry(panel, call_verification_required="1")
    _status, body = _get(f"{panel}/anfragen")
    assert '<span class="blocked">Rückrufprüfung ausstehend</span>' in body


def test_list_verified_or_not_required_has_no_blocked_class(panel: str) -> None:
    _iid = _create_inquiry(panel)  # call_verification_required not set → not_required
    _status, body = _get(f"{panel}/anfragen")
    assert '<span class="blocked">' not in body


def test_search_finds_by_inquiry_source(panel: str) -> None:
    _iid = _create_inquiry(panel, inquiry_source="website_form")
    _status, body = _get(f"{panel}/anfragen?q=website_form")
    assert "Website-Anfrage" in body


def test_search_finds_by_intake_subject(panel: str) -> None:
    iid = _create_inquiry(panel, intake_subject="EinzigartigerSuchbegriff")
    _status, body = _get(f"{panel}/anfragen?q=EinzigartigerSuchbegriff")
    assert iid[:8] in body


def test_detail_shows_website_anfrage_label(panel: str) -> None:
    iid = _create_inquiry(panel, inquiry_source="website_form")
    _status, body = _get(f"{panel}/inquiry/{iid}")
    assert "Website-Anfrage" in body


def test_detail_website_form_banner_present(panel: str) -> None:
    iid = _create_inquiry(panel, inquiry_source="website_form")
    _status, body = _get(f"{panel}/inquiry/{iid}")
    assert (
        "Website-Anfrage — noch kein Auftrag. Nur Intake-Kontext, "
        "keine Küchenfreigabe." in body
    )
    assert 'class="proposal-banner"' in body


def test_detail_banner_absent_for_non_website_source(panel: str) -> None:
    iid = _create_inquiry(panel, inquiry_source="manual")
    _status, body = _get(f"{panel}/inquiry/{iid}")
    assert "noch kein Auftrag" not in body


def test_detail_intake_message_remains_escaped(panel: str) -> None:
    iid = _create_inquiry(
        panel,
        inquiry_source="website_form",
        intake_message="<script>alert(1)</script> & special",
    )
    _status, body = _get(f"{panel}/inquiry/{iid}")
    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;" in body


def test_verification_button_text_unchanged_for_website_form(panel: str) -> None:
    iid = _create_inquiry(
        panel, inquiry_source="website_form", call_verification_required="1"
    )
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
        iid = _create_inquiry(base, inquiry_source="website_form")
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
    iid = _create_inquiry(
        panel, inquiry_source="website_form", call_verification_required="1"
    )
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(f"{panel}/inquiry/{iid}/convert", {})
    assert exc.value.code == 400
