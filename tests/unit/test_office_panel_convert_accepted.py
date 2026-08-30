"""Panel wiring for convert-accepted (4E-2): button, command, redirect."""

from __future__ import annotations

from tests.helpers.order_seed import seed_order

import base64
import json
import queue
import re
import sqlite3
import uuid
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from http.server import HTTPServer
from pathlib import Path

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
from catering_system.services.operational_core_service import OperationalCoreService
from catering_system.services.order_service import OrderService
from catering_system.ui.office_api import create_office_api_server
from tests.helpers.offer_pdf_static_content import (
    fake_offer_pdf_static_content,
)
from catering_system.ui.office_panel_http import (
    create_office_panel_server,
    csrf_token_for_password,
)
from catering_system.ui.remote_core_client import RemoteCoreClient

_PASSWORD = "test-pw"
_AUTH = "Basic " + base64.b64encode(f"office:{_PASSWORD}".encode()).decode()
_CSRF_TOKEN = csrf_token_for_password(_PASSWORD)
_API_TOKEN = "test-remote-api-token"
_API_AUTH = {"Authorization": f"Bearer {_API_TOKEN}"}
_SNAPSHOT_ID = "77777777-7777-4777-8777-777777777771"
_VARIANT_ID = "44444444-4444-4444-8444-444444444441"
_POSITION_ID = "88888888-8888-4888-8888-888888888881"
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


@pytest.fixture(autouse=True)
def _fixed_business_date(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "catering_system.ui.office_api_views.berlin_today",
        lambda: date(2026, 7, 15),
    )


def _seed(db_path: Path) -> dict[str, str]:
    inquiries = SQLiteInquiryRepository(db_path)
    orders = SQLiteOrderRepository(db_path)
    inquiry_service = InquiryService(inquiries)
    OrderService(orders)
    core = OperationalCoreService(orders)
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
    cancelled_src = inquiry_service.create_inquiry(
        event_date=date(2026, 10, 2),
        inquiry_source="manual",
        crm_stage="Neue Anfrage",
        customer_linkage={},
        time_window_text="abends",
        location_text="Kiel",
        guest_count_estimate=40,
        planning_mode="caterer_suggestion",
        call_verification_required=False,
        call_verification_status="not_required",
        contact_email="kunde@example.com",
        contact_phone="+49301234567",
    )
    cancelled_order, _version = seed_order(orders, cancelled_src)
    core.cancel_order(cancelled_order.order_id)
    offer_ready = inquiry_service.create_inquiry(
        event_date=date(2026, 10, 3),
        inquiry_source="manual",
        crm_stage="Neue Anfrage",
        customer_linkage={},
        time_window_text="abends",
        location_text="Angebot-Stadt",
        guest_count_estimate=40,
        planning_mode="caterer_suggestion",
        call_verification_required=False,
        call_verification_status="not_required",
        contact_email="kunde@example.com",
        contact_phone="+49301234567",
    )
    inquiries.close()
    orders.close()
    return {
        "inquiry_convertible": inquiry.inquiry_id,
        "inquiry_cancelled_order": cancelled_src.inquiry_id,
        "inquiry_offer_ready": offer_ready.inquiry_id,
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


def _valid_offer_snapshot(*, inquiry_id: str) -> dict[str, object]:
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
                "label": "Variante A",
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


def _accept_offer_via_api(api_url: str, inquiry_id: str) -> None:
    status, body = _api_post(
        f"{api_url}/office/v1/inquiries/{inquiry_id}/prepare-offer",
        args={"snapshot": _valid_offer_snapshot(inquiry_id=inquiry_id)},
    )
    assert status == 201
    offer_id = body["offer_id"]
    version_id = body["offer_version_id"]
    assert (
        _api_post(
            f"{api_url}/office/v1/offers/{offer_id}/versions/{version_id}/mark-sent",
            args=_MARK_SENT_ARGS,
        )[0]
        == 200
    )
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
    with urllib.request.urlopen(req) as resp:
        return resp.status, resp.url, resp.read().decode("utf-8")


def _extract_hidden(html: str, name: str) -> str:
    match = re.search(rf'name="{re.escape(name)}" value="([^"]*)"', html)
    assert match, f"missing hidden field {name!r}"
    return match.group(1)


def _post_convert_accepted(panel_url: str, inquiry_id: str) -> tuple[int, str, str]:
    _status, detail = _get(f"{panel_url}/inquiry/{inquiry_id}")
    form = re.search(
        r"(<form[^>]*convert-accepted[^>]*>.*?</form>)",
        detail,
        re.DOTALL,
    )
    fields: dict[str, str] = {}
    if form is not None:
        block = form.group(0)
        if "_command_id" in block:
            fields["_command_id"] = _extract_hidden(block, "_command_id")
        fields["payment_method"] = "BAR_VOR_ORT"
    return _post(f"{panel_url}/inquiry/{inquiry_id}/convert-accepted", fields)


def _active_order_count(db: Path, inquiry_id: str) -> int:
    conn = sqlite3.connect(db)
    try:
        return conn.execute(
            """
            SELECT COUNT(*) FROM orders
            WHERE source_inquiry_id = ? AND cancelled_at IS NULL
            """,
            (inquiry_id,),
        ).fetchone()[0]
    finally:
        conn.close()


@pytest.fixture()
def direct_world(tmp_path: Path):
    db = tmp_path / "convert-accepted.db"
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


def test_accepted_offer_button_creates_order_and_disappears(direct_world) -> None:
    panel_url, api_url, ids, db = direct_world
    inquiry_id = ids["inquiry_convertible"]
    _accept_offer_via_api(api_url, inquiry_id)

    _status, detail = _get(f"{panel_url}/inquiry/{inquiry_id}")
    assert "Angenommenes Angebot in Auftrag überführen" in detail
    assert 'action="/inquiry/' in detail and "convert-accepted" in detail
    assert (
        "Dieses angenommene Angebot wird jetzt in einen Auftrag umgewandelt." in detail
    )
    assert 'name="payment_method" required' in detail
    assert "Vorkasse" in detail
    assert "Rechnung" in detail
    assert "Bar vor Ort" in detail

    status, final_url, _body = _post_convert_accepted(panel_url, inquiry_id)
    assert status == 200
    assert "/order/" in final_url
    order_id = final_url.rstrip("/").rsplit("/", 1)[-1]
    assert _active_order_count(db, inquiry_id) == 1

    _status, detail_after = _get(f"{panel_url}/inquiry/{inquiry_id}")
    assert "Angenommenes Angebot in Auftrag überführen" not in detail_after
    assert "Auftrag vorhanden" in detail_after
    assert f"/order/{order_id}" in detail_after


def test_converted_storno_shows_open_link_not_create_button(direct_world) -> None:
    panel_url, api_url, ids, db = direct_world
    inquiry_id = ids["inquiry_offer_ready"]
    _accept_offer_via_api(api_url, inquiry_id)

    offers = SQLiteOfferRepository(db)
    offer = offers.get_by_source_inquiry_id(inquiry_id)
    assert offer is not None
    version_id = offer.versions[0].offer_version_id
    acceptance_id = offer.acceptance_evidence.acceptance_id  # type: ignore[union-attr]
    variant_id = offer.acceptance_evidence.accepted_variant_id  # type: ignore[union-attr]
    offers.close()

    status, body = _api_post(
        f"{api_url}/office/v1/offers/{offer.offer_id}/versions/{version_id}/convert-accepted",
        args={
            "accepted_variant_id": variant_id,
            "acceptance_id": acceptance_id,
            "payment_method": "RECHNUNG",
        },
    )
    assert status == 201
    order_id = body["order_id"]
    orders = SQLiteOrderRepository(db)
    order = orders.get_order(order_id)
    assert order is not None
    cancel_status, _cancel_body = _api_post(
        f"{api_url}/office/v1/orders/{order_id}/cancel",
        args={},
        expect={"updated_at": order.updated_at.isoformat()},
    )
    orders.close()
    assert cancel_status == 200

    _status, detail = _get(f"{panel_url}/inquiry/{inquiry_id}")
    assert "Angenommenes Angebot in Auftrag überführen" not in detail
    assert "Auftrag öffnen" in detail
    assert "Auftrag erstellen" not in detail


def test_convert_accepted_replay_does_not_create_second_order(direct_world) -> None:
    panel_url, api_url, ids, db = direct_world
    inquiry_id = ids["inquiry_convertible"]
    _accept_offer_via_api(api_url, inquiry_id)

    _post_convert_accepted(panel_url, inquiry_id)
    assert _active_order_count(db, inquiry_id) == 1

    status, final_url, _body = _post(
        f"{panel_url}/inquiry/{inquiry_id}/convert-accepted",
        {"payment_method": "BAR_VOR_ORT"},
    )
    assert status == 200
    assert "/order/" in final_url
    assert _active_order_count(db, inquiry_id) == 1


def test_remote_panel_convert_accepted_parity(tmp_path: Path) -> None:
    db = tmp_path / "remote-convert.db"
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
    _accept_offer_via_api(api_url, inquiry_id)
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
        _status, detail = _get(f"{panel_url}/inquiry/{inquiry_id}")
        assert "Angenommenes Angebot in Auftrag überführen" in detail
        status, final_url, _body = _post_convert_accepted(panel_url, inquiry_id)
        assert status == 200
        assert "/order/" in final_url
        assert _active_order_count(db, inquiry_id) == 1
    finally:
        panel_server.shutdown()
        panel_server.server_close()
        api_server.shutdown()
        api_server.server_close()
