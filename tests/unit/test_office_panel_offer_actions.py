"""Panel offer lifecycle actions (5B-3): mark-sent, acceptance, convert."""

from __future__ import annotations

import base64
import json
import queue
import re
import sqlite3
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import date
from http.server import HTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from catering_system.domain.offer_snapshot import compute_snapshot_hash
from catering_system.repositories.core_transaction import (
    CoreCommandExecutor,
    open_core_connection,
)
from catering_system.repositories.sqlite_inquiry_repository import (
    SQLiteInquiryRepository,
)
from catering_system.repositories.sqlite_offer_repository import (
    SQLiteOfferRepository,
)
from catering_system.repositories.sqlite_order_repository import (
    SQLiteOrderRepository,
)
from catering_system.repositories.sqlite_payment_reminder_repository import (
    SQLitePaymentReminderRepository,
)
from catering_system.services.inquiry_service import InquiryService
from catering_system.ui.office_api import create_office_api_server
from catering_system.ui.office_panel_http import (
    create_office_panel_server,
    csrf_token_for_password,
    inquiry_command_error_message,
)
from catering_system.ui.office_panel_offer_detail import render_offer_detail
from catering_system.ui.office_panel_views import (
    OfficePageContext,
    parse_datetime_local_berlin,
)
from catering_system.ui.remote_core_client import RemoteCoreClient

_PASSWORD = "test-pw"
_AUTH = "Basic " + base64.b64encode(f"office:{_PASSWORD}".encode()).decode()
_CSRF_TOKEN = csrf_token_for_password(_PASSWORD)
_API_TOKEN = "test-remote-api-token"
_API_AUTH = {"Authorization": f"Bearer {_API_TOKEN}"}
_SNAPSHOT_ID = "77777777-7777-4777-8777-777777777771"
_VARIANT_ID = "44444444-4444-4444-8444-444444444441"
_OTHER_VARIANT = "44444444-4444-4444-8444-444444444442"
_POSITION_ID = "88888888-8888-4888-8888-888888888881"
_BERLIN = ZoneInfo("Europe/Berlin")
_MARK_SENT_ARGS = {
    "sent_at": "2026-07-15T10:00:00+00:00",
    "channel": "email",
    "recipient_reference": "customer@example.invalid",
    "evidence_reference": "mail-123",
}
_RECORD_ACCEPTANCE_ARGS = {
    "accepted_variant_id": _VARIANT_ID,
    "accepted_at": "2026-07-15T11:00:00+00:00",
    "channel": "email",
    "evidence_reference": "reply-1",
}


def _past_datetime_local() -> str:
    from datetime import datetime, timedelta

    from catering_system.ui.office_api_views import BERLIN

    return (datetime.now(BERLIN) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")


def _seed(db_path: Path) -> dict[str, str]:
    inquiries = SQLiteInquiryRepository(db_path)
    inquiry_service = InquiryService(inquiries)
    inquiry = inquiry_service.create_inquiry(
        event_date=date(2026, 10, 1),
        inquiry_source="manual",
        crm_stage="Neue Anfrage",
        customer_linkage={},
        time_window_text="mittags",
        location_text="Hamburg",
        guest_count_estimate=25,
        planning_mode="caterer_suggestion",
        call_verification_required=False,
        call_verification_status="not_required",
        contact_email="kunde@example.com",
        contact_phone="+49301234567",
        intake_subject="Sommerfest",
    )
    rejected = inquiry_service.create_inquiry(
        event_date=date(2026, 10, 3),
        inquiry_source="manual",
        crm_stage="Neue Anfrage",
        customer_linkage={},
        time_window_text="abends",
        location_text="Lübeck",
        guest_count_estimate=30,
        planning_mode="caterer_suggestion",
        call_verification_required=False,
        call_verification_status="not_required",
        contact_email="kunde@example.com",
        contact_phone="+49301234567",
    )
    inquiries.close()
    return {
        "inquiry_convertible": inquiry.inquiry_id,
        "inquiry_rejected": rejected.inquiry_id,
    }


def _run_server_in_thread(build_server) -> tuple[str, HTTPServer]:
    ready: queue.Queue = queue.Queue()

    def run() -> None:
        server = build_server()
        ready.put(server)
        server.serve_forever()

    threading.Thread(target=run, daemon=True).start()
    server = ready.get(timeout=5)
    host, port = server.server_address[:2]
    return f"http://{host}:{port}", server


def _valid_offer_snapshot(
    *, inquiry_id: str, variant_label: str = "Variante A"
) -> dict:
    payload: dict[str, object] = {
        "schema_version": "offer_snapshot_v1",
        "source": "fingerfood-configurator-backend",
        "source_draft_id": "draft-1",
        "inquiry_id": inquiry_id,
        "snapshot_id": _SNAPSHOT_ID,
        "snapshot_created_at": "2026-07-15T08:30:00+00:00",
        "valid_until": "2026-07-29",
        "currency": "EUR",
        "recipient": {
            "company_name": "Example company",
            "contact_name": "Example contact",
            "email": "customer@example.invalid",
            "postal_address": "Customer-visible recipient address",
        },
        "event": {
            "event_date": "2026-08-20",
            "time_window_text": "18:00–22:00",
            "location_text": "Hamburg",
            "guest_count": 80,
            "planning_mode": "caterer_suggestion",
        },
        "customer_text": {
            "title": "Sommerfest",
            "introduction": "Customer-visible introduction",
            "notes": "Customer-visible conditions and notes",
        },
        "payment_terms": {
            "method": "RECHNUNG",
            "customer_visible_text": "Zahlung per Rechnung",
        },
        "calculator": {
            "name": "fingerfood-backend",
            "calculator_revision": "future-revision",
            "catalog_revision": "future-revision",
            "tax_revision": "future-revision",
        },
        "variants": [
            {
                "variant_id": _VARIANT_ID,
                "label": variant_label,
                "description": "Customer-visible alternative",
                "positions": [
                    {
                        "position_id": _POSITION_ID,
                        "kind": "catalog",
                        "catalog_item_id": "catalog-1",
                        "name": "Fingerfood Paket",
                        "description": "Frozen description",
                        "composition": "Frozen composition",
                        "quantity_mode": "total",
                        "quantity": "80",
                        "unit_label": "Stück",
                        "unit_net_cents": 290,
                        "net_total_cents": 23200,
                        "vat_rate_percent": 7,
                        "vat_amount_cents": 1624,
                        "gross_total_cents": 24824,
                        "notes": "Frozen customization",
                        "related_position_id": None,
                    }
                ],
                "totals": {
                    "net_cents": 23200,
                    "vat_7_base_cents": 23200,
                    "vat_7_amount_cents": 1624,
                    "vat_19_base_cents": 0,
                    "vat_19_amount_cents": 0,
                    "gross_cents": 24824,
                },
            }
        ],
    }
    payload["snapshot_hash"] = compute_snapshot_hash(payload)
    return payload


def _api_post(
    url: str,
    *,
    args: dict | None = None,
    expect: dict | None = None,
) -> tuple[int, dict]:
    body = json.dumps(
        {
            "command_id": str(uuid.uuid4()),
            "expect": expect or {},
            "args": args or {},
        }
    ).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Authorization", _API_AUTH["Authorization"])
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode())


def _prepare_offer(api_url: str, inquiry_id: str) -> tuple[str, str]:
    status, body = _api_post(
        f"{api_url}/office/v1/inquiries/{inquiry_id}/prepare-offer",
        args={"snapshot": _valid_offer_snapshot(inquiry_id=inquiry_id)},
    )
    assert status == 201
    return body["offer_id"], body["offer_version_id"]


def _mark_sent_api(api_url: str, offer_id: str, version_id: str) -> None:
    assert (
        _api_post(
            f"{api_url}/office/v1/offers/{offer_id}/versions/{version_id}/mark-sent",
            args=_MARK_SENT_ARGS,
        )[0]
        == 200
    )


def _record_acceptance_api(api_url: str, offer_id: str, version_id: str) -> None:
    assert (
        _api_post(
            f"{api_url}/office/v1/offers/{offer_id}/versions/{version_id}/record-acceptance",
            args=_RECORD_ACCEPTANCE_ARGS,
        )[0]
        == 200
    )


def _start_direct_panel(db: Path) -> tuple[str, HTTPServer]:
    def build() -> HTTPServer:
        conn = open_core_connection(db)
        return create_office_panel_server(
            SQLiteInquiryRepository.from_connection(conn),
            SQLiteOrderRepository.from_connection(conn),
            _PASSWORD,
            host="127.0.0.1",
            port=0,
            command_executor=CoreCommandExecutor(conn),
            payment_reminder_repo=SQLitePaymentReminderRepository.from_connection(conn),
            offer_repo=SQLiteOfferRepository.from_connection(conn),
            ui_version="v2",
        )

    return _run_server_in_thread(build)


def _get(url: str) -> tuple[int, str]:
    req = urllib.request.Request(url)
    req.add_header("Authorization", _AUTH)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


def _post(url: str, fields: dict[str, str]) -> tuple[int, str, str]:
    payload = dict(fields)
    payload.setdefault("_csrf_token", _CSRF_TOKEN)
    req = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(payload).encode(),
        method="POST",
    )
    req.add_header("Authorization", _AUTH)
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, resp.url, resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.url, exc.read().decode("utf-8")


def _extract_hidden(html: str, name: str) -> str:
    match = re.search(rf'name="{re.escape(name)}" value="([^"]*)"', html)
    assert match, f"missing hidden field {name!r}"
    return match.group(1)


def _offer_form_fields(html: str, action_suffix: str) -> dict[str, str]:
    match = re.search(
        rf"(<form[^>]*{re.escape(action_suffix)}[^>]*>.*?</form>)",
        html,
        re.DOTALL,
    )
    assert match, f"missing form for {action_suffix!r}"
    block = match.group(0)
    fields: dict[str, str] = {}
    if "_command_id" in block:
        fields["_command_id"] = _extract_hidden(block, "_command_id")
    return fields


@pytest.fixture()
def direct_world(tmp_path: Path):
    db = tmp_path / "offer-actions.db"
    ids = _seed(db)
    api_url, api_server = _run_server_in_thread(
        lambda: create_office_api_server(str(db), _API_TOKEN, "127.0.0.1", 0)
    )
    panel_url, panel_server = _start_direct_panel(db)
    try:
        yield panel_url, api_url, ids, db
    finally:
        for server in (panel_server, api_server):
            server.shutdown()
            server.server_close()


def test_prepared_shows_mark_sent_form_only(direct_world) -> None:
    panel_url, api_url, ids, _db = direct_world
    offer_id, _version_id = _prepare_offer(api_url, ids["inquiry_convertible"])
    _status, html = _get(f"{panel_url}/offer/{offer_id}")
    assert "Als gesendet markieren" in html
    assert 'action="/offer/' in html and "/mark-sent" in html
    assert "Annahme erfassen" not in html
    assert "In Auftrag umwandeln" not in html


def test_sent_shows_sent_lifecycle_actions(direct_world) -> None:
    panel_url, api_url, ids, _db = direct_world
    offer_id, version_id = _prepare_offer(api_url, ids["inquiry_convertible"])
    _mark_sent_api(api_url, offer_id, version_id)
    _status, html = _get(f"{panel_url}/offer/{offer_id}")
    assert "Annahme erfassen" in html
    assert "/record-acceptance" in html
    assert "Kunde lehnt ab" in html
    assert "/record-rejection" in html
    assert "Angebot zurückziehen" in html
    assert "/record-withdrawal" in html
    assert "Als gesendet markieren" not in html
    assert "In Auftrag umwandeln" not in html


def test_accepted_shows_convert_form_only(direct_world) -> None:
    panel_url, api_url, ids, _db = direct_world
    offer_id, version_id = _prepare_offer(api_url, ids["inquiry_convertible"])
    _mark_sent_api(api_url, offer_id, version_id)
    _record_acceptance_api(api_url, offer_id, version_id)
    _status, html = _get(f"{panel_url}/offer/{offer_id}")
    assert "In Auftrag umwandeln" in html
    assert "/offer/" in html and "/convert" in html
    assert "Als gesendet markieren" not in html
    assert "Annahme erfassen" not in html


def test_converted_shows_order_link_without_actions(direct_world) -> None:
    panel_url, api_url, ids, _db = direct_world
    offer_id, version_id = _prepare_offer(api_url, ids["inquiry_convertible"])
    _mark_sent_api(api_url, offer_id, version_id)
    _record_acceptance_api(api_url, offer_id, version_id)
    offers = SQLiteOfferRepository(_db)
    offer = offers.get(offer_id)
    assert offer is not None and offer.acceptance_evidence is not None
    convert_status, convert_body = _api_post(
        f"{api_url}/office/v1/offers/{offer_id}/versions/{version_id}/convert-accepted",
        args={
            "accepted_variant_id": offer.acceptance_evidence.accepted_variant_id,
            "acceptance_id": offer.acceptance_evidence.acceptance_id,
        },
    )
    offers.close()
    assert convert_status == 201
    order_id = convert_body["order_id"]
    _status, html = _get(f"{panel_url}/offer/{offer_id}")
    assert f"/order/{order_id}" in html
    assert "Auftrag öffnen" in html
    assert "Als gesendet markieren" not in html
    assert "Annahme erfassen" not in html
    assert "In Auftrag umwandeln" not in html


def test_expired_offer_has_no_lifecycle_actions(direct_world) -> None:
    panel_url, api_url, ids, _db = direct_world
    inquiry_id = ids["inquiry_rejected"]
    snapshot = _valid_offer_snapshot(inquiry_id=inquiry_id)
    snapshot["valid_until"] = "2020-01-01"
    snapshot["snapshot_hash"] = compute_snapshot_hash(snapshot)
    status, body = _api_post(
        f"{api_url}/office/v1/inquiries/{inquiry_id}/prepare-offer",
        args={"snapshot": snapshot},
    )
    assert status == 201
    offer_id = body["offer_id"]
    version_id = body["offer_version_id"]
    _mark_sent_api(api_url, offer_id, version_id)
    _status, html = _get(f"{panel_url}/offer/{offer_id}")
    assert "Als gesendet markieren" not in html
    assert "Annahme erfassen" not in html
    assert "In Auftrag umwandeln" not in html


def test_second_mark_sent_shows_german_error(direct_world) -> None:
    panel_url, api_url, ids, _db = direct_world
    offer_id, version_id = _prepare_offer(api_url, ids["inquiry_convertible"])
    _mark_sent_api(api_url, offer_id, version_id)
    status, _url, body = _post(
        f"{panel_url}/offer/{offer_id}/mark-sent",
        {
            "sent_at": "2026-07-16T16:00",
            "channel": "email",
            "recipient_reference": "kunde@example.invalid",
            "evidence_reference": "Nochmal",
        },
    )
    assert status == 400
    assert inquiry_command_error_message("sent_recording_blocked") in body


def test_second_acceptance_shows_german_error(direct_world) -> None:
    panel_url, api_url, ids, _db = direct_world
    offer_id, version_id = _prepare_offer(api_url, ids["inquiry_convertible"])
    _mark_sent_api(api_url, offer_id, version_id)
    _record_acceptance_api(api_url, offer_id, version_id)
    status, _url, body = _post(
        f"{panel_url}/offer/{offer_id}/record-acceptance",
        {
            "accepted_variant_id": _VARIANT_ID,
            "accepted_at": "2026-07-16T15:00",
            "channel": "email",
            "evidence_reference": "Telefonische Bestätigung",
        },
    )
    assert status == 400
    assert inquiry_command_error_message("acceptance_blocked") in body


def test_mark_sent_requires_evidence_reference(direct_world) -> None:
    panel_url, api_url, ids, _db = direct_world
    offer_id, _version_id = _prepare_offer(api_url, ids["inquiry_convertible"])
    _status, html = _get(f"{panel_url}/offer/{offer_id}")
    fields = _offer_form_fields(html, "/mark-sent")
    fields.update(
        {
            "sent_at": "2026-07-16T14:30",
            "channel": "email",
            "recipient_reference": "kunde@example.invalid",
            "evidence_reference": "",
        }
    )
    status, _url, body = _post(f"{panel_url}/offer/{offer_id}/mark-sent", fields)
    assert status == 400
    assert "evidence_reference is required" in body or "Fehler" in body


def test_datetime_local_converts_to_berlin_iso(direct_world) -> None:
    panel_url, api_url, ids, db = direct_world
    offer_id, _version_id = _prepare_offer(api_url, ids["inquiry_convertible"])
    _status, html = _get(f"{panel_url}/offer/{offer_id}")
    fields = _offer_form_fields(html, "/mark-sent")
    fields.update(
        {
            "sent_at": _past_datetime_local(),
            "channel": "email",
            "recipient_reference": "kunde@example.invalid",
            "evidence_reference": "E-Mail vom 16.07.2026",
        }
    )
    status, final_url, _body = _post(f"{panel_url}/offer/{offer_id}/mark-sent", fields)
    assert status == 200
    assert final_url.endswith(f"/offer/{offer_id}")
    expected = parse_datetime_local_berlin(_past_datetime_local()).isoformat()
    offers = SQLiteOfferRepository(db)
    offer = offers.get(offer_id)
    offers.close()
    assert offer is not None
    assert offer.sent_evidence[0].sent_at.isoformat() == expected


def test_tampered_variant_rejected_by_core(direct_world) -> None:
    panel_url, api_url, ids, _db = direct_world
    offer_id, version_id = _prepare_offer(api_url, ids["inquiry_convertible"])
    _mark_sent_api(api_url, offer_id, version_id)
    _status, html = _get(f"{panel_url}/offer/{offer_id}")
    fields = _offer_form_fields(html, "/record-acceptance")
    fields.update(
        {
            "accepted_variant_id": _OTHER_VARIANT,
            "accepted_at": "2026-07-16T15:00",
            "channel": "email",
            "evidence_reference": "Telefonische Bestätigung",
        }
    )
    status, _url, body = _post(
        f"{panel_url}/offer/{offer_id}/record-acceptance",
        fields,
    )
    assert status == 400
    assert (
        inquiry_command_error_message("invalid_variant") in body
        or "accepted variant does not belong" in body
    )


def test_convert_redirects_to_created_order(direct_world) -> None:
    panel_url, api_url, ids, db = direct_world
    offer_id, version_id = _prepare_offer(api_url, ids["inquiry_convertible"])
    _mark_sent_api(api_url, offer_id, version_id)
    _record_acceptance_api(api_url, offer_id, version_id)
    _status, html = _get(f"{panel_url}/offer/{offer_id}")
    fields = _offer_form_fields(html, "/convert")
    fields["accepted_variant_id"] = _extract_hidden(html, "accepted_variant_id")
    fields["acceptance_id"] = _extract_hidden(html, "acceptance_id")
    status, final_url, _body = _post(f"{panel_url}/offer/{offer_id}/convert", fields)
    assert status == 200
    assert "/order/" in final_url
    order_id = final_url.rstrip("/").rsplit("/", 1)[-1]
    conn = sqlite3.connect(db)
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM orders WHERE source_inquiry_id = ? AND cancelled_at IS NULL",
            (ids["inquiry_convertible"],),
        ).fetchone()[0]
    finally:
        conn.close()
    assert count == 1
    _status, order_html = _get(f"{panel_url}/order/{order_id}")
    assert order_html


def test_inquiry_convert_accepted_still_works(direct_world) -> None:
    panel_url, api_url, ids, db = direct_world
    inquiry_id = ids["inquiry_convertible"]
    offer_id, version_id = _prepare_offer(api_url, inquiry_id)
    _mark_sent_api(api_url, offer_id, version_id)
    _record_acceptance_api(api_url, offer_id, version_id)
    _status, detail = _get(f"{panel_url}/inquiry/{inquiry_id}")
    assert "Angenommenes Angebot in Auftrag überführen" in detail
    fields = _offer_form_fields(detail, "convert-accepted")
    status, final_url, _body = _post(
        f"{panel_url}/inquiry/{inquiry_id}/convert-accepted",
        fields,
    )
    assert status == 200
    assert "/order/" in final_url


def test_html_escaping_in_variant_label() -> None:
    detail: dict[str, object] = {
        "offer_id": "11111111-1111-4111-8111-111111111111",
        "inquiry_id": "22222222-2222-4222-8222-222222222222",
        "offer_version_id": "33333333-3333-4333-8333-333333333331",
        "commercial_state": "Sent",
        "acceptance_id": None,
        "versions": [
            {
                "version": 1,
                "state": "Sent",
                "event_date": "2026-08-01",
                "valid_until": "2026-07-31",
                "time_window_text": "18:00",
                "location_text": "Hamburg",
                "guest_count": 50,
                "planning_mode": "caterer_suggestion",
                "variants": [
                    {
                        "variant_id": _VARIANT_ID,
                        "name": '<script>alert("x")</script>',
                    }
                ],
            }
        ],
        "sent_evidence": {"sent_at": "2026-07-15T10:00:00+00:00", "channel": "email"},
        "acceptance": None,
        "history": [{"at": "2026-07-15T08:00:00+00:00", "label": "Angebot erstellt"}],
    }
    from catering_system.ui.office_panel_offer_detail import OfferDetailFormFields

    html = render_offer_detail(
        detail,
        context=OfficePageContext(csrf_token=_CSRF_TOKEN),
        forms=OfferDetailFormFields(csrf_input="", command_fields=""),
    )
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_remote_offer_mark_sent_parity(tmp_path: Path) -> None:
    db = tmp_path / "remote-offer-actions.db"
    ids = _seed(db)
    inquiry_id = ids["inquiry_convertible"]
    api_url, api_server = _run_server_in_thread(
        lambda: create_office_api_server(str(db), _API_TOKEN, "127.0.0.1", 0)
    )
    offer_id, _version_id = _prepare_offer(api_url, inquiry_id)
    remote = RemoteCoreClient(api_url, _API_TOKEN)
    panel_url, panel_server = _run_server_in_thread(
        lambda: create_office_panel_server(
            remote,
            remote,
            _PASSWORD,
            host="127.0.0.1",
            port=0,
            remote=remote,
            ui_version="v2",
        )
    )
    try:
        _status, html = _get(f"{panel_url}/offer/{offer_id}")
        fields = _offer_form_fields(html, "/mark-sent")
        fields.update(
            {
                "sent_at": _past_datetime_local(),
                "channel": "email",
                "recipient_reference": "kunde@example.invalid",
                "evidence_reference": "E-Mail vom 16.07.2026",
            }
        )
        status, final_url, _body = _post(
            f"{panel_url}/offer/{offer_id}/mark-sent",
            fields,
        )
        assert status == 200
        assert final_url.endswith(f"/offer/{offer_id}")
        _status, detail = _get(f"{panel_url}/offer/{offer_id}")
        assert "Annahme erfassen" in detail
    finally:
        panel_server.shutdown()
        panel_server.server_close()
        api_server.shutdown()
        api_server.server_close()


def test_sent_offer_shows_rejection_and_withdrawal_actions(direct_world) -> None:
    panel_url, api_url, ids, _db = direct_world
    offer_id, version_id = _prepare_offer(api_url, ids["inquiry_convertible"])
    _mark_sent_api(api_url, offer_id, version_id)
    _status, html = _get(f"{panel_url}/offer/{offer_id}")
    assert "Annahme erfassen" in html
    assert "Kunde lehnt ab" in html
    assert "Angebot zurückziehen" in html
    assert f'action="/offer/{offer_id}/record-rejection"' in html
    assert f'action="/offer/{offer_id}/record-withdrawal"' in html


def test_record_rejection_through_panel(direct_world) -> None:
    panel_url, api_url, ids, _db = direct_world
    offer_id, version_id = _prepare_offer(api_url, ids["inquiry_convertible"])
    _mark_sent_api(api_url, offer_id, version_id)
    _status, html = _get(f"{panel_url}/offer/{offer_id}")
    fields = _offer_form_fields(html, "/record-rejection")
    fields.update(
        {
            "rejected_at": _past_datetime_local(),
            "evidence_reference": "Telefonische Absage",
        }
    )
    status, final_url, _body = _post(
        f"{panel_url}/offer/{offer_id}/record-rejection",
        fields,
    )
    assert status == 200
    assert final_url.endswith(f"/offer/{offer_id}")
    _status, detail = _get(f"{panel_url}/offer/{offer_id}")
    assert "Abgelehnt" in detail
    assert "Kunde lehnt ab" not in detail
    assert "Annahme erfassen" not in detail


def test_record_withdrawal_through_panel(direct_world) -> None:
    panel_url, api_url, ids, _db = direct_world
    offer_id, version_id = _prepare_offer(api_url, ids["inquiry_convertible"])
    _mark_sent_api(api_url, offer_id, version_id)
    _status, html = _get(f"{panel_url}/offer/{offer_id}")
    fields = _offer_form_fields(html, "/record-withdrawal")
    fields["reason"] = "Angebot zurückgezogen"
    status, final_url, _body = _post(
        f"{panel_url}/offer/{offer_id}/record-withdrawal",
        fields,
    )
    assert status == 200
    assert final_url.endswith(f"/offer/{offer_id}")
    _status, detail = _get(f"{panel_url}/offer/{offer_id}")
    assert "Zurückgezogen" in detail
    assert "Angebot zurückziehen" not in detail


def test_rejected_offer_has_no_lifecycle_actions(direct_world) -> None:
    panel_url, api_url, ids, _db = direct_world
    offer_id, version_id = _prepare_offer(api_url, ids["inquiry_convertible"])
    _mark_sent_api(api_url, offer_id, version_id)
    assert (
        _api_post(
            f"{api_url}/office/v1/offers/{offer_id}/versions/{version_id}/record-rejection",
            args={"rejected_at": "2026-07-15T12:00:00+00:00"},
        )[0]
        == 200
    )
    _status, html = _get(f"{panel_url}/offer/{offer_id}")
    assert "Annahme erfassen" not in html
    assert "Kunde lehnt ab" not in html
    assert "Angebot zurückziehen" not in html
    assert "Abgelehnt" in html
