"""CUSTOMER_DOCUMENT_PROJECTION_V1-E — remote preview exact-key parse."""

from __future__ import annotations

import json
import threading
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pytest

from catering_system.ui.remote_core_client import RemoteCoreClient, RemoteCoreError

_TOKEN = "test-remote-preview-token"
_ORDER_ID = "22222222-2222-4222-8222-222222222222"
_VERSION_ID = "33333333-3333-4333-8333-333333333331"
_SNAPSHOT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_OFFER_ID = "11111111-1111-4111-8111-111111111111"
_OFFER_VERSION_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
_POSITION_ID = "55555555-5555-4555-8555-555555555551"


def _serve(handler_cls: type[BaseHTTPRequestHandler]) -> tuple[str, HTTPServer]:
    server = HTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    return f"http://{host}:{port}", server


def _eligible_payload() -> dict[str, Any]:
    return {
        "document_type": "ORDER_CONFIRMATION",
        "eligible": True,
        "fulfillment_mode": "PICKUP",
        "blockers": [],
        "warnings": [],
        "recipient": {
            "name": "Anna",
            "email": "anna@example.invalid",
            "company_name": "ACME GmbH",
            "phone": "+49301234567",
            "invoice_address": None,
            "delivery_address": None,
            "delivery_address_differs": False,
        },
        "event": {
            "order_id": _ORDER_ID,
            "order_version_id": _VERSION_ID,
            "version_number": 1,
            "event_date": "2026-08-20",
            "time_window_text": "18:00–22:00",
            "location_text": "Hamburg",
            "guest_count_estimate": 80,
            "planning_mode": "caterer_suggestion",
        },
        "commercial": {
            "snapshot_id": _SNAPSHOT_ID,
            "source_offer_id": _OFFER_ID,
            "source_offer_version_id": _OFFER_VERSION_ID,
            "variant_label": "Variante A",
        },
        "positions": [
            {
                "position_id": _POSITION_ID,
                "kind": "catalog",
                "name": "Fingerfood Paket",
                "description": None,
                "composition": None,
                "quantity": "80 Stück",
                "unit_label": "Stück",
                "unit_net_cents": 290,
                "net_total_cents": 23200,
                "vat_rate_percent": 7,
                "vat_amount_cents": 1624,
                "gross_total_cents": 24824,
                "related_position_id": None,
            }
        ],
        "payment_method": "RECHNUNG",
        "payment_customer_visible_text": "Zahlung per Rechnung",
        "net_total_cents": 23200,
        "vat_total_cents": 1624,
        "gross_total_cents": 24824,
    }


def _handler_with(body: dict[str, Any] | None, *, status: int = 200):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            return

        def do_GET(self) -> None:  # noqa: N802
            if status == 404:
                payload = {"error": "not_found"}
                raw = json.dumps(payload).encode()
                self.send_response(404)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
                return
            assert body is not None
            raw = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    return Handler


def test_preview_order_confirmation_parses_eligible_payload() -> None:
    base, server = _serve(_handler_with(_eligible_payload()))
    try:
        client = RemoteCoreClient(base, _TOKEN)
        preview = client.confirmation_document_service.preview_order_confirmation(
            _ORDER_ID
        )
    finally:
        server.shutdown()
        server.server_close()
    assert preview.eligible is True
    assert preview.blockers == ()
    assert preview.warnings == ()
    assert preview.recipient.name == "Anna"
    assert preview.commercial_reference is not None
    assert preview.gross_total_cents == 24824


def test_preview_order_confirmation_parses_multi_blockers() -> None:
    payload = _eligible_payload()
    payload["eligible"] = False
    payload["blockers"] = [
        {"code": "MISSING_CUSTOMER_CONTACT", "detail": None},
        {"code": "MISSING_COMMERCIAL_SNAPSHOT", "detail": "no row"},
    ]
    payload["commercial"] = None
    payload["positions"] = []
    payload["payment_method"] = None
    payload["payment_customer_visible_text"] = None
    payload["net_total_cents"] = None
    payload["vat_total_cents"] = None
    payload["gross_total_cents"] = None
    base, server = _serve(_handler_with(payload))
    try:
        client = RemoteCoreClient(base, _TOKEN)
        preview = client.confirmation_document_service.preview_order_confirmation(
            _ORDER_ID
        )
    finally:
        server.shutdown()
        server.server_close()
    assert preview.eligible is False
    assert [b.code for b in preview.blockers] == [
        "MISSING_CUSTOMER_CONTACT",
        "MISSING_COMMERCIAL_SNAPSHOT",
    ]


def test_preview_order_confirmation_parses_warning() -> None:
    payload = _eligible_payload()
    payload["warnings"] = ["DELIVERY_ADDRESS_DIFFERS_FROM_INVOICE"]
    payload["recipient"]["invoice_address"] = {
        "street": "Büro 1",
        "postal_code": "20095",
        "city": "Hamburg",
        "country": "DE",
    }
    payload["recipient"]["delivery_address"] = {
        "street": "Event 9",
        "postal_code": "20457",
        "city": "Hamburg",
        "country": "DE",
    }
    payload["recipient"]["delivery_address_differs"] = True
    base, server = _serve(_handler_with(payload))
    try:
        client = RemoteCoreClient(base, _TOKEN)
        preview = client.confirmation_document_service.preview_order_confirmation(
            _ORDER_ID
        )
    finally:
        server.shutdown()
        server.server_close()
    assert preview.eligible is True
    assert preview.warnings == ("DELIVERY_ADDRESS_DIFFERS_FROM_INVOICE",)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.pop("eligible"),
        lambda p: p.pop("blockers"),
        lambda p: p.pop("warnings"),
        lambda p: p.__setitem__("eligible", "yes"),
        lambda p: p.__setitem__("blockers", "MISSING_CUSTOMER_NAME"),
        lambda p: p.__setitem__("extra", 1),
    ],
)
def test_preview_order_confirmation_fail_closed_on_bad_payload(mutate) -> None:
    payload = _eligible_payload()
    mutate(payload)
    base, server = _serve(_handler_with(payload))
    try:
        client = RemoteCoreClient(base, _TOKEN)
        with pytest.raises(RemoteCoreError) as exc:
            client.confirmation_document_service.preview_order_confirmation(_ORDER_ID)
        assert exc.value.code == "invalid_response"
        assert exc.value.unavailable is True
    finally:
        server.shutdown()
        server.server_close()


def test_preview_order_confirmation_404_maps_not_found() -> None:
    base, server = _serve(_handler_with(None, status=404))
    try:
        client = RemoteCoreClient(base, _TOKEN)
        with pytest.raises(RemoteCoreError) as exc:
            client.confirmation_document_service.preview_order_confirmation(
                str(uuid.uuid4())
            )
        assert (exc.value.status, exc.value.code) == (404, "not_found")
        assert exc.value.unavailable is False
    finally:
        server.shutdown()
        server.server_close()
