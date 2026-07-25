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
from dataclasses import replace
from datetime import date
from http.server import HTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from catering_system.domain.customer_document_projection import CustomerAddress
from catering_system.domain.inquiry_customer_snapshot import InquiryCustomerSnapshot
from catering_system.domain.offer_pdf import OfferPdfStaticContent
from catering_system.domain.offer_snapshot import compute_snapshot_hash
from catering_system.repositories.core_transaction import (
    CoreCommandExecutor,
    open_core_connection,
)
from catering_system.repositories.sqlite_inquiry_repository import (
    SQLiteInquiryRepository,
)
from catering_system.repositories.sqlite_offer_document_snapshot_repository import (
    SQLiteOfferDocumentSnapshotRepository,
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
from tests.helpers.offer_pdf_static_content import (
    fake_offer_pdf_static_content,
)
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
    *,
    inquiry_id: str,
    variant_label: str = "Variante A",
    variant_id: str = _VARIANT_ID,
    position_id: str = _POSITION_ID,
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
                "variant_id": variant_id,
                "label": variant_label,
                "description": "Customer-visible alternative",
                "positions": [
                    {
                        "position_id": position_id,
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


def _prepare_offer(
    api_url: str,
    inquiry_id: str,
    *,
    variant_id: str = _VARIANT_ID,
    position_id: str = _POSITION_ID,
) -> tuple[str, str]:
    status, body = _api_post(
        f"{api_url}/office/v1/inquiries/{inquiry_id}/prepare-offer",
        args={
            "snapshot": _valid_offer_snapshot(
                inquiry_id=inquiry_id,
                variant_id=variant_id,
                position_id=position_id,
            )
        },
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


def _pickup_eligible_snapshot() -> InquiryCustomerSnapshot:
    return InquiryCustomerSnapshot(
        company_name="ACME GmbH",
        contact_name="Anna",
        email="anna@example.invalid",
        phone="+49301234567",
        invoice_address=CustomerAddress(
            street="Bürostraße 1",
            postal_code="20095",
            city="Hamburg",
            country="DE",
        ),
        delivery_address=None,
        delivery_address_mode="SAME_AS_INVOICE",
    )


def _set_customer_snapshot(
    db: Path, inquiry_id: str, snapshot: InquiryCustomerSnapshot
) -> None:
    inquiries = SQLiteInquiryRepository(db)
    inquiry = inquiries.get_by_id(inquiry_id)
    assert inquiry is not None
    inquiries.update(replace(inquiry, customer_snapshot=snapshot))
    inquiries.close()


def _set_fulfillment_mode(
    api_url: str, inquiry_id: str, *, mode: str = "PICKUP"
) -> None:
    _status, detail = _api_get(f"{api_url}/office/v1/inquiries/{inquiry_id}")
    status, _body = _api_post(
        f"{api_url}/office/v1/inquiries/{inquiry_id}/fulfillment-mode",
        args={"fulfillment_mode": mode},
        expect={"updated_at": detail["updated_at"]},
    )
    assert status == 200


def _create_offer_document(
    api_url: str, offer_id: str, offer_version_id: str, variant_id: str
) -> dict:
    status, body = _api_post(
        f"{api_url}/office/v1/offers/{offer_id}/offer-document",
        args={
            "offer_version_id": offer_version_id,
            "offer_variant_id": variant_id,
            "created_by": "office-panel-test",
        },
    )
    assert status in (200, 201)
    return body


def _prepare_offer_with_document(
    api_url: str,
    db: Path,
    inquiry_id: str,
    *,
    variant_id: str = _VARIANT_ID,
    position_id: str = _POSITION_ID,
) -> tuple[str, str, dict]:
    """Prepares a PICKUP-eligible offer and freezes its OfferDocumentSnapshot
    via the real Office API, so the panel's PDF download link/route has a
    genuine immutable snapshot to read."""
    _set_customer_snapshot(db, inquiry_id, _pickup_eligible_snapshot())
    _set_fulfillment_mode(api_url, inquiry_id, mode="PICKUP")
    offer_id, offer_version_id = _prepare_offer(
        api_url, inquiry_id, variant_id=variant_id, position_id=position_id
    )
    document = _create_offer_document(api_url, offer_id, offer_version_id, variant_id)
    return offer_id, offer_version_id, document


def _start_direct_panel(
    db: Path, *, static_content: OfferPdfStaticContent | None = None
) -> tuple[str, HTTPServer]:
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
            offer_document_repo=SQLiteOfferDocumentSnapshotRepository.from_connection(
                conn
            ),
            offer_pdf_static_content=static_content or fake_offer_pdf_static_content(),
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


def _get_raw(url: str) -> tuple[int, bytes, dict[str, str]]:
    req = urllib.request.Request(url)
    req.add_header("Authorization", _AUTH)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers)


def _api_get(url: str) -> tuple[int, dict]:
    req = urllib.request.Request(url)
    req.add_header("Authorization", _API_AUTH["Authorization"])
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode() or "{}")


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
        lambda: create_office_api_server(
            str(db),
            _API_TOKEN,
            "127.0.0.1",
            0,
            offer_pdf_static_content=fake_offer_pdf_static_content(),
        )
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
                "offer_version_id": "33333333-3333-4333-8333-333333333331",
                "version": 1,
                "state": "Sent",
                "created_at": "2026-07-15T08:00:00+00:00",
                "sent_at": "2026-07-15T10:00:00+00:00",
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
        "history": [
            {"at": "2026-07-15T08:00:00+00:00", "label": "Version 1 vorbereitet"}
        ],
    }
    from catering_system.ui.office_panel_offer_detail import OfferDetailFormFields

    html = render_offer_detail(
        detail,
        context=OfficePageContext(csrf_token=_CSRF_TOKEN),
        forms=OfferDetailFormFields(csrf_input="", command_fields=""),
    )
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "Neue Version vorbereiten" in html


def test_expired_offer_detail_shows_prepare_next_without_link() -> None:
    detail: dict[str, object] = {
        "offer_id": "11111111-1111-4111-8111-111111111111",
        "inquiry_id": "22222222-2222-4222-8222-222222222222",
        "offer_version_id": "33333333-3333-4333-8333-333333333331",
        "commercial_state": "Expired",
        "acceptance_id": None,
        "versions": [
            {
                "offer_version_id": "33333333-3333-4333-8333-333333333331",
                "version": 1,
                "state": "Expired",
                "created_at": "2026-07-01T08:00:00+00:00",
                "sent_at": "2026-07-01T10:00:00+00:00",
                "event_date": "2026-08-01",
                "valid_until": "2026-07-01",
                "time_window_text": "18:00",
                "location_text": "Hamburg",
                "guest_count": 50,
                "planning_mode": "caterer_suggestion",
                "variants": [{"variant_id": _VARIANT_ID, "name": "Variante A"}],
            }
        ],
        "sent_evidence": {"sent_at": "2026-07-01T10:00:00+00:00", "channel": "email"},
        "acceptance": None,
        "history": [
            {"at": "2026-07-01T08:00:00+00:00", "label": "Version 1 vorbereitet"}
        ],
    }
    from catering_system.ui.office_panel_offer_detail import OfferDetailFormFields

    html = render_offer_detail(
        detail,
        context=OfficePageContext(csrf_token=_CSRF_TOKEN),
        forms=OfferDetailFormFields(csrf_input="", command_fields=""),
        revision_prefill_url=None,
    )
    assert "Neue Version vorbereiten" in html
    assert "offer-revision-link" not in html
    assert "Angebotsversionen" in html
    assert "✓ Aktuell" in html


def test_expired_offer_detail_shows_prepare_next_with_link() -> None:
    detail: dict[str, object] = {
        "offer_id": "11111111-1111-4111-8111-111111111111",
        "inquiry_id": "22222222-2222-4222-8222-222222222222",
        "offer_version_id": "33333333-3333-4333-8333-333333333331",
        "commercial_state": "Expired",
        "acceptance_id": None,
        "versions": [
            {
                "offer_version_id": "33333333-3333-4333-8333-333333333331",
                "version": 1,
                "state": "Expired",
                "created_at": "2026-07-01T08:00:00+00:00",
                "sent_at": "2026-07-01T10:00:00+00:00",
                "event_date": "2026-08-01",
                "valid_until": "2026-07-01",
                "time_window_text": "18:00",
                "location_text": "Hamburg",
                "guest_count": 50,
                "planning_mode": "caterer_suggestion",
                "variants": [{"variant_id": _VARIANT_ID, "name": "Variante A"}],
            }
        ],
        "sent_evidence": {"sent_at": "2026-07-01T10:00:00+00:00", "channel": "email"},
        "acceptance": None,
        "history": [
            {"at": "2026-07-01T08:00:00+00:00", "label": "Version 1 vorbereitet"}
        ],
    }
    from catering_system.ui.office_panel_offer_detail import OfferDetailFormFields

    html = render_offer_detail(
        detail,
        context=OfficePageContext(csrf_token=_CSRF_TOKEN),
        forms=OfferDetailFormFields(csrf_input="", command_fields=""),
        revision_prefill_url="/configurator?offer=11111111-1111-4111-8111-111111111111",
    )
    assert 'class="offer-revision-link"' in html
    assert "/configurator?offer=" in html


def test_acceptance_blocked_newer_version_error_message() -> None:
    from catering_system.ui.office_panel_http import office_command_error_message

    assert office_command_error_message("acceptance_blocked_newer_version_exists") == (
        "Annahme nicht möglich: Eine neuere Angebotsversion ist bereits vorbereitet."
    )
    assert office_command_error_message(
        "ValueError: acceptance_blocked_newer_version_exists (offer_id='x')"
    ).startswith("Annahme nicht möglich:")


def test_remote_offer_mark_sent_parity(tmp_path: Path) -> None:
    db = tmp_path / "remote-offer-actions.db"
    ids = _seed(db)
    inquiry_id = ids["inquiry_convertible"]
    api_url, api_server = _run_server_in_thread(
        lambda: create_office_api_server(
            str(db),
            _API_TOKEN,
            "127.0.0.1",
            0,
            offer_pdf_static_content=fake_offer_pdf_static_content(),
        )
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


# --- OFFER_PDF_PANEL_DOWNLOAD_V1 — PDF download button + proxy route -------


def test_offer_detail_shows_pdf_download_button_when_snapshot_exists(
    direct_world,
) -> None:
    panel_url, api_url, ids, db = direct_world
    offer_id, offer_version_id, _document = _prepare_offer_with_document(
        api_url, db, ids["inquiry_convertible"]
    )
    _status, html = _get(f"{panel_url}/offer/{offer_id}")
    assert "PDF herunterladen" in html
    assert (
        f"/offer/{offer_id}/offer-document/pdf?offer_version_id={offer_version_id}"
        in html
    )


def test_offer_detail_hides_pdf_download_button_when_snapshot_missing(
    direct_world,
) -> None:
    panel_url, api_url, ids, _db = direct_world
    offer_id, _version_id = _prepare_offer(api_url, ids["inquiry_convertible"])
    _status, html = _get(f"{panel_url}/offer/{offer_id}")
    assert "PDF herunterladen" not in html
    # Regression check: the rest of the Prepared-state detail page (existing
    # lifecycle actions) must still render unchanged around the new link.
    assert "Als versendet erfassen" in html or "sent_at" in html


def test_offer_detail_pdf_button_coexists_with_mark_sent_action(direct_world) -> None:
    panel_url, api_url, ids, db = direct_world
    offer_id, _version_id, _document = _prepare_offer_with_document(
        api_url, db, ids["inquiry_convertible"]
    )
    _status, html = _get(f"{panel_url}/offer/{offer_id}")
    assert "PDF herunterladen" in html
    fields = _offer_form_fields(html, "/mark-sent")
    assert fields is not None  # mark-sent form still present alongside the link


def test_panel_pdf_download_returns_valid_pdf(direct_world) -> None:
    panel_url, api_url, ids, db = direct_world
    offer_id, offer_version_id, _document = _prepare_offer_with_document(
        api_url, db, ids["inquiry_convertible"]
    )
    status, data, headers = _get_raw(
        f"{panel_url}/offer/{offer_id}/offer-document/pdf"
        f"?offer_version_id={offer_version_id}"
    )
    assert status == 200
    assert data[:5] == b"%PDF-"
    assert headers.get("Content-Type") == "application/pdf"


def test_panel_pdf_download_content_disposition_filename_preserved(
    direct_world,
) -> None:
    panel_url, api_url, ids, db = direct_world
    offer_id, offer_version_id, document = _prepare_offer_with_document(
        api_url, db, ids["inquiry_convertible"]
    )
    document_reference = document["snapshot"]["document_reference"]
    _status, _data, headers = _get_raw(
        f"{panel_url}/offer/{offer_id}/offer-document/pdf"
        f"?offer_version_id={offer_version_id}"
    )
    assert headers.get("Content-Disposition") == (
        f'attachment; filename="{document_reference}.pdf"'
    )


def test_panel_pdf_download_missing_snapshot_returns_404(direct_world) -> None:
    panel_url, api_url, ids, _db = direct_world
    offer_id, offer_version_id = _prepare_offer(api_url, ids["inquiry_convertible"])
    status, _data, _headers = _get_raw(
        f"{panel_url}/offer/{offer_id}/offer-document/pdf"
        f"?offer_version_id={offer_version_id}"
    )
    assert status == 404


def test_panel_pdf_download_missing_version_query_returns_404(direct_world) -> None:
    panel_url, api_url, ids, db = direct_world
    offer_id, _version_id, _document = _prepare_offer_with_document(
        api_url, db, ids["inquiry_convertible"]
    )
    status, _data, _headers = _get_raw(
        f"{panel_url}/offer/{offer_id}/offer-document/pdf"
    )
    assert status == 404


def test_panel_pdf_download_cross_offer_access_returns_404_without_leak(
    direct_world,
) -> None:
    panel_url, api_url, ids, db = direct_world
    offer_a_id, version_a_id, _doc_a = _prepare_offer_with_document(
        api_url, db, ids["inquiry_convertible"]
    )
    offer_b_id, version_b_id, doc_b = _prepare_offer_with_document(
        api_url,
        db,
        ids["inquiry_rejected"],
        variant_id=_OTHER_VARIANT,
        position_id=str(uuid.uuid4()),
    )
    status, data, _headers = _get_raw(
        f"{panel_url}/offer/{offer_a_id}/offer-document/pdf"
        f"?offer_version_id={version_b_id}"
    )
    assert status == 404
    reference_b = doc_b["snapshot"]["document_reference"]
    assert reference_b.encode() not in data

    status2, _data2, _headers2 = _get_raw(
        f"{panel_url}/offer/{offer_b_id}/offer-document/pdf"
        f"?offer_version_id={version_a_id}"
    )
    assert status2 == 404


def test_panel_repeated_pdf_download_does_not_create_additional_snapshot(
    direct_world,
) -> None:
    panel_url, api_url, ids, db = direct_world
    offer_id, offer_version_id, document = _prepare_offer_with_document(
        api_url, db, ids["inquiry_convertible"]
    )
    original_snapshot_id = document["offer_document_snapshot_id"]
    url = (
        f"{panel_url}/offer/{offer_id}/offer-document/pdf"
        f"?offer_version_id={offer_version_id}"
    )
    status1, data1, _h1 = _get_raw(url)
    status2, data2, _h2 = _get_raw(url)
    assert status1 == status2 == 200
    assert data1 == data2

    documents = SQLiteOfferDocumentSnapshotRepository(db)
    snapshot = documents.get_by_offer_version_id(offer_version_id)
    documents.close()
    assert snapshot is not None
    assert snapshot.offer_document_snapshot_id == original_snapshot_id


def test_direct_pdf_download_renderer_failure_shows_clear_german_message(
    tmp_path: Path,
) -> None:
    db = tmp_path / "offer-pdf-422.db"
    ids = _seed(db)
    api_url, api_server = _run_server_in_thread(
        lambda: create_office_api_server(
            str(db),
            _API_TOKEN,
            "127.0.0.1",
            0,
            offer_pdf_static_content=fake_offer_pdf_static_content(),
        )
    )
    oversized_content = OfferPdfStaticContent(
        company_legal_name="TEST GmbH [PLATZHALTER]",
        company_address_lines=("Teststraße 1", "20095 Hamburg"),
        acceptance_statement="[TEST PLACEHOLDER — NOT APPROVED CUSTOMER WORDING]",
        footer_note="Sehr langer Footertext. " * 40,
    )
    panel_url, panel_server = _start_direct_panel(db, static_content=oversized_content)
    try:
        offer_id, offer_version_id, _document = _prepare_offer_with_document(
            api_url, db, ids["inquiry_convertible"]
        )
        status, body, _headers = _get_raw(
            f"{panel_url}/offer/{offer_id}/offer-document/pdf"
            f"?offer_version_id={offer_version_id}"
        )
        assert status == 422
        text = body.decode("utf-8")
        assert "PDF konnte nicht erzeugt werden" in text
        assert "Traceback" not in text
    finally:
        panel_server.shutdown()
        panel_server.server_close()
        api_server.shutdown()
        api_server.server_close()


def test_remote_panel_pdf_download_never_exposes_office_api_token(
    tmp_path: Path,
) -> None:
    db = tmp_path / "remote-offer-pdf.db"
    ids = _seed(db)
    inquiry_id = ids["inquiry_convertible"]
    api_url, api_server = _run_server_in_thread(
        lambda: create_office_api_server(
            str(db),
            _API_TOKEN,
            "127.0.0.1",
            0,
            offer_pdf_static_content=fake_offer_pdf_static_content(),
        )
    )
    offer_id, offer_version_id, _document = _prepare_offer_with_document(
        api_url, db, inquiry_id
    )
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
        assert "PDF herunterladen" in html
        assert _API_TOKEN not in html

        status, data, headers = _get_raw(
            f"{panel_url}/offer/{offer_id}/offer-document/pdf"
            f"?offer_version_id={offer_version_id}"
        )
        assert status == 200
        assert data[:5] == b"%PDF-"
        assert headers.get("Content-Type") == "application/pdf"
        assert _API_TOKEN.encode() not in data
        assert all(_API_TOKEN not in value for value in headers.values())
    finally:
        panel_server.shutdown()
        panel_server.server_close()
        api_server.shutdown()
        api_server.server_close()
