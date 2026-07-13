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
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from catering_system.intake.website_form_adapter import intake_from_website_form
from catering_system.repositories.in_memory_inquiry_repository import (
    InMemoryInquiryRepository,
)
from catering_system.repositories.in_memory_order_repository import (
    InMemoryOrderRepository,
)
from catering_system.ui.office_panel import (
    OfficePageContext,
    OfficePanel,
    create_office_panel_server,
    parse_proposal_payload,
    render_proposal_preview_form,
)
from catering_system.ui.office_panel_http import csrf_token_for_password

_PASSWORD = "test-pw"
_AUTH = "Basic " + base64.b64encode(f"office:{_PASSWORD}".encode()).decode()
_CSRF_TOKEN = csrf_token_for_password(_PASSWORD)


@pytest.fixture()
def panel():
    inquiry_repo = InMemoryInquiryRepository()
    order_repo = InMemoryOrderRepository()
    server = create_office_panel_server(
        inquiry_repo, order_repo, _PASSWORD, host="127.0.0.1", port=0
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    yield f"http://{host}:{port}"
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
    }
    data.update(overrides)
    _status, url, _body = _post(f"{base}/inquiry/new", data)
    return url.rsplit("/", 1)[-1]  # inquiry id from redirect target


def _convert(base: str, inquiry_id: str) -> str:
    _status, url, _body = _post(f"{base}/inquiry/{inquiry_id}/convert", {})
    return url.rsplit("/", 1)[-1]  # order id


def test_page_context_badge_does_not_leak_between_renders() -> None:
    with_badge = render_proposal_preview_form(
        context=OfficePageContext(rueckruf_count=3)
    )
    without_badge = render_proposal_preview_form()

    assert '<span class="badge">3</span>' in with_badge
    assert '<span class="badge">' not in without_badge


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
        assert "form-action 'self'" in response.headers["Content-Security-Policy"]
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
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(f"{panel}/inquiry/{iid}/convert", {})
    assert exc.value.code == 400


def test_verify_then_convert(panel: str) -> None:
    iid = _create_inquiry(panel, call_verification_required="1")
    _status, _url, body = _post(f"{panel}/inquiry/{iid}/verify", {})
    assert "verifiziert" in body
    oid = _convert(panel, iid)
    status, body = _get(f"{panel}/order/{oid}")
    assert status == 200
    assert "v1" in body


def test_converted_inquiry_shows_order_link_instead_of_button(panel: str) -> None:
    iid = _create_inquiry(panel)
    oid = _convert(panel, iid)
    _status, body = _get(f"{panel}/inquiry/{iid}")
    assert "Auftrag vorhanden" in body and oid[:8] in body
    assert "In Auftrag umwandeln" not in body


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
    assert "Küchenzettel" in sheet and "Hamburg" in sheet and "mittags" in sheet


def test_cancel_shows_storniert_and_hides_actions(panel: str) -> None:
    iid = _create_inquiry(panel)
    oid = _convert(panel, iid)
    _status, _url, body = _post(f"{panel}/order/{oid}/cancel", {})
    assert "STORNIERT" in body
    assert "Auftrag stornieren" not in body  # actions hidden
    assert "Auftrag storniert" in body  # operational reason shown, human label
    assert "Küchenzettel" in body  # history stays viewable


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


def test_reconvert_possible_after_storno(panel: str) -> None:
    """A cancelled order must not suppress the convert button (Storno semantics)."""
    iid = _create_inquiry(panel)
    oid = _convert(panel, iid)
    _post(f"{panel}/order/{oid}/cancel", {})
    _status, body = _get(f"{panel}/inquiry/{iid}")
    assert "(storniert)" in body
    assert "In Auftrag umwandeln" in body  # button back after Storno
    oid2 = _convert(panel, iid)
    assert oid2 != oid
    _status, body = _get(f"{panel}/inquiry/{iid}")
    assert "In Auftrag umwandeln" not in body  # active order suppresses it again


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
        oid = _convert(base, iid)
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


def _make_auerswald_stub(resolved: list, hits: list | None = None) -> HTTPServer:
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
                remaining = [
                    it for it in _AUERSWALD_ITEMS if it["call_id"] not in resolved
                ]
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
    assert counts["Neue Anfragen prüfen"] == 0
    assert counts["Druckbestätigung fehlt"] == 0
    assert counts["Aufträge noch nicht wirksam"] == 0
    assert counts["Versandfreigabe blockiert"] == 0
    assert "Stornierte Aufträge prüfen" not in body  # no cancelled orders yet
    assert "Diese Woche" in body
    assert "keine wirksamen Aufträge diese Woche" in body
    assert "Neue Anfragen" in body
    assert "keine neuen Anfragen." in body
    assert "Aufträge mit nächstem Schritt" in body
    assert "keine offenen Schritte." in body


def test_attention_counts_reflect_new_inquiry_and_unconfirmed_order(panel: str) -> None:
    iid = _create_inquiry(panel)
    _status, body = _get(f"{panel}/")
    assert _attention_counts(body)["Neue Anfragen prüfen"] == 1

    oid = _convert(panel, iid)
    _status, body = _get(f"{panel}/")
    counts = _attention_counts(body)
    # Converting removes it from "Neue Anfragen prüfen" (now has an order)...
    assert counts["Neue Anfragen prüfen"] == 0
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
    today = date.today().isoformat()
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
        "<h2>Neue Anfragen</h2>"
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
        assert "Neue Anfragen" in body
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
    assert _attention_counts(body)["Neue Anfragen prüfen"] == 7
    assert body.count("<button>In Auftrag umwandeln</button>") == 5
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
    )
    order, v1 = panel.order_service.convert_inquiry_to_order(inquiry)
    return panel, order, v1


def test_next_step_targets_latest_version_when_no_candidate_set() -> None:
    panel, order, v1 = _panel_with_order()
    action_html = panel._next_step_action(order)
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
    action_html = panel._next_step_action(order)
    # Candidate is v1, not the higher version_number v2 -> v1 wins.
    assert f'value="{v1.order_version_id}"' in action_html
    assert v2.order_version_id not in action_html


def test_next_step_never_offers_effective_before_print_confirmed() -> None:
    """The real invariant this resolution exists to protect: Core itself
    refuses make_order_version_effective() for an unprinted version."""
    panel, order, v1 = _panel_with_order()
    action_html = panel._next_step_action(order)
    assert "print-confirm" in action_html
    assert "effective" not in action_html

    panel.core.confirm_kitchen_print(order.order_id, v1.order_version_id)
    order = panel._orders.get_order(order.order_id)
    action_html = panel._next_step_action(order)
    assert "Wirksam machen" in action_html
    assert f'action="/order/{order.order_id}/effective"' in action_html


def test_next_step_falls_back_to_latest_when_candidate_is_foreign() -> None:
    """Defensive case: a candidate_order_version_id that doesn't resolve to
    any real version of this order must not crash the Startseite."""
    from dataclasses import replace

    panel, order, v1 = _panel_with_order()
    broken = replace(order, candidate_order_version_id="does-not-exist")
    action_html = panel._next_step_action(broken)
    assert f'value="{v1.order_version_id}"' in action_html


def test_next_step_empty_when_order_has_no_versions() -> None:
    from dataclasses import replace

    panel, order, _v1 = _panel_with_order()
    fake_order = replace(order, order_id="unknown-order-id")
    assert panel._next_step_action(fake_order) == ""


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
            "submission_id": "office-workflow-e2e",
        },
    )

    queue = office.render_queue(None)
    detail = office.render_inquiry(inquiry.inquiry_id)
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

    order, version = office.order_service.convert_inquiry_to_order(verified)
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
