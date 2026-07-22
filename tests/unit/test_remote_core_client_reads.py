"""RemoteCoreClient read-endpoint parsing coverage."""

from __future__ import annotations

import json
import threading
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import cast

import pytest

from catering_system.ui.remote_core_client import RemoteCoreClient, RemoteCoreError

_TOKEN = "test-remote-token"


def _serve(handler_cls: type[BaseHTTPRequestHandler]) -> tuple[str, HTTPServer]:
    server = HTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    return f"http://{host}:{port}", server


def _valid_queue_body() -> dict[str, object]:
    inquiry_id = str(uuid.uuid4())
    order_id = str(uuid.uuid4())
    return {
        "attention": {
            "neue_anfragen": 0,
            "druck_fehlt": 0,
            "nicht_wirksam": 0,
            "versand_blockiert": 0,
            "aenderungen_warten_auf_kuechendruck": 0,
            "pausiert": 0,
            "storniert": 0,
        },
        "week": {
            "iso_year": 2026,
            "iso_week": 30,
            "entries": [
                {
                    "order_id": order_id,
                    "event_date": "2026-10-01",
                    "time_window_text": "mittags",
                    "location_text": "Hamburg",
                    "guest_count_estimate": 25,
                }
            ],
            "total_count": 1,
            "truncated": False,
        },
        "neue_anfragen_top": [
            {
                "inquiry_id": inquiry_id,
                "event_date": "2026-10-01",
                "time_window_text": "abends",
                "location_text": "Berlin",
                "guest_count_estimate": 40,
                "inquiry_source": "manual",
                "crm_stage": "Neue Anfrage",
                "planning_mode": "caterer_suggestion",
                "call_verification_required": False,
                "call_verification_status": "not_required",
                "created_at": "2026-07-14T10:00:00+02:00",
                "updated_at": "2026-07-14T10:00:00+02:00",
                "next_action": "verify",
            }
        ],
        "auftraege_top": [
            {
                "order_id": order_id,
                "source_inquiry_id": inquiry_id,
                "created_at": "2026-07-14T10:00:00+02:00",
                "updated_at": "2026-07-14T10:00:00+02:00",
                "candidate_order_version_id": None,
                "effective_order_version_id": None,
                "cancelled_at": None,
                "blocker_reason": None,
                "next_action": None,
                "operational_pause_active": False,
            }
        ],
        "pausiert_top": [
            {
                "order_id": order_id,
                "source_inquiry_id": inquiry_id,
                "created_at": "2026-07-14T10:00:00+02:00",
                "updated_at": "2026-07-14T10:00:00+02:00",
                "candidate_order_version_id": None,
                "effective_order_version_id": None,
                "cancelled_at": None,
                "blocker_reason": "paused",
                "next_action": None,
                "operational_pause_active": True,
                "operational_pause_reason_code": "office_hold",
            }
        ],
    }


def test_queue_view_accepts_valid_payload() -> None:
    body = json.dumps(_valid_queue_body()).encode()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args: object) -> None:
            pass

    url, server = _serve(Handler)
    try:
        parsed = RemoteCoreClient(url, _TOKEN).queue_view()
        assert parsed["attention"]["neue_anfragen"] == 0
        assert len(parsed["neue_anfragen_top"]) == 1
    finally:
        server.shutdown()
        server.server_close()


def test_work_center_accepts_valid_payload() -> None:
    payload = {
        "rueckrufe_open": 1,
        "missed_calls_open": 0,
        "offers_waiting": 2,
        "offers_accepted": 0,
        "upcoming_orders": 3,
        "open_tasks": 4,
        "today_calendar_entries": 5,
        "pending_order_changes": 0,
    }
    body = json.dumps(payload).encode()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args: object) -> None:
            pass

    url, server = _serve(Handler)
    try:
        parsed = RemoteCoreClient(url, _TOKEN).work_center()
        assert parsed["open_tasks"] == 4
    finally:
        server.shutdown()
        server.server_close()


def test_list_offers_accepts_valid_payload() -> None:
    offer_id = str(uuid.uuid4())
    inquiry_id = str(uuid.uuid4())
    payload = {
        "offers": [
            {
                "offer_id": offer_id,
                "inquiry_id": inquiry_id,
                "state": "Prepared",
                "event_date": "2026-10-01",
                "valid_until": "2026-10-15",
            }
        ]
    }
    body = json.dumps(payload).encode()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args: object) -> None:
            pass

    url, server = _serve(Handler)
    try:
        parsed = RemoteCoreClient(url, _TOKEN).list_offers()
        assert parsed["offers"][0]["offer_id"] == offer_id
    finally:
        server.shutdown()
        server.server_close()


def test_offer_queue_accepts_valid_payload() -> None:
    offer_id = str(uuid.uuid4())
    inquiry_id = str(uuid.uuid4())
    version_id = str(uuid.uuid4())
    payload = {
        "today": "2026-07-15",
        "sections": [
            {
                "group": "action_required",
                "label": "Aktion erforderlich",
                "count": 1,
                "items": [
                    {
                        "offer_id": offer_id,
                        "inquiry_id": inquiry_id,
                        "offer_version_id": version_id,
                        "version_number": 1,
                        "state": "Prepared",
                        "state_label": "Vorbereitet",
                        "queue_group": "action_required",
                        "queue_subkind": "prepared",
                        "next_action": "mark_sent",
                        "next_action_label": "Als gesendet markieren",
                        "customer_display": "Müller GmbH",
                        "intake_subject": "Hochzeit",
                        "event_date": "2026-08-01",
                        "guest_count": 80,
                        "valid_until": "2026-07-31",
                        "days_until_valid_until": 16,
                        "days_overdue": None,
                        "prepared_at": "2026-07-15T08:00:00+00:00",
                        "sent_at": None,
                    }
                ],
            },
            {
                "group": "overdue",
                "label": "Frist überschritten",
                "count": 0,
                "items": [],
            },
            {
                "group": "history",
                "label": "Abgeschlossen / Verlauf",
                "count": 0,
                "items": [],
            },
        ],
        "total_count": 1,
        "limit": 100,
        "offset": 0,
    }
    body = json.dumps(payload).encode()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args: object) -> None:
            pass

    url, server = _serve(Handler)
    try:
        parsed = RemoteCoreClient(url, _TOKEN).offer_queue()
        assert parsed["total_count"] == 1
        assert parsed["sections"][0]["items"][0]["offer_id"] == offer_id
    finally:
        server.shutdown()
        server.server_close()


def test_list_offers_rejects_unknown_state() -> None:
    payload = {
        "offers": [
            {
                "offer_id": str(uuid.uuid4()),
                "inquiry_id": str(uuid.uuid4()),
                "state": "Mystery",
                "event_date": "2026-10-01",
                "valid_until": "2026-10-15",
            }
        ]
    }
    body = json.dumps(payload).encode()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args: object) -> None:
            pass

    url, server = _serve(Handler)
    try:
        with pytest.raises(RemoteCoreError) as exc:
            RemoteCoreClient(url, _TOKEN).list_offers()
        assert exc.value.code == "invalid_response"
    finally:
        server.shutdown()
        server.server_close()


def test_queue_view_rejects_invalid_iso_week() -> None:
    body_dict = _valid_queue_body()
    week = cast(dict[str, object], body_dict["week"])
    week["iso_week"] = 99
    body = json.dumps(body_dict).encode()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args: object) -> None:
            pass

    url, server = _serve(Handler)
    try:
        with pytest.raises(RemoteCoreError) as exc:
            RemoteCoreClient(url, _TOKEN).queue_view()
        assert exc.value.code == "invalid_response"
    finally:
        server.shutdown()
        server.server_close()


def test_queue_view_rejects_truncated_week_mismatch() -> None:
    body_dict = _valid_queue_body()
    week = cast(dict[str, object], body_dict["week"])
    week["total_count"] = 99
    week["truncated"] = False
    body = json.dumps(body_dict).encode()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args: object) -> None:
            pass

    url, server = _serve(Handler)
    try:
        with pytest.raises(RemoteCoreError) as exc:
            RemoteCoreClient(url, _TOKEN).queue_view()
        assert exc.value.code == "invalid_response"
    finally:
        server.shutdown()
        server.server_close()


def _json_handler(payload: dict[str, object]) -> type[BaseHTTPRequestHandler]:
    body = json.dumps(payload).encode()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args: object) -> None:
            pass

    return Handler


def test_list_contacts_accepts_valid_payload() -> None:
    contact_key = "linkage:11111111-1111-4111-8111-111111111111"
    payload = {
        "contacts": [
            {
                "contact_key": contact_key,
                "identity_source": "inquiry",
                "display_name": "Example Contact",
                "email": "customer@example.invalid",
                "phone": None,
                "inquiry_count": 1,
                "open_inquiries": 1,
                "active_orders": 0,
                "linked_order_count": 0,
                "contact_status": "interessent",
                "last_activity": "2026-07-14T10:00:00+02:00",
            }
        ]
    }
    url, server = _serve(_json_handler(payload))
    try:
        parsed = RemoteCoreClient(url, _TOKEN).list_contacts()
        assert parsed["contacts"][0]["contact_key"] == contact_key
    finally:
        server.shutdown()
        server.server_close()


def test_list_catalog_dishes_accepts_valid_payload() -> None:
    dish_id = str(uuid.uuid4())
    payload = {
        "dishes": [
            {
                "dish_id": dish_id,
                "name": "Fingerfood",
                "current_unit_net_cents": 290,
                "price_display": "2,90 EUR",
                "allergens": ["A"],
                "allergen_labels": ["Gluten"],
                "active": True,
            }
        ],
        "total_count": 1,
        "truncated": False,
    }
    url, server = _serve(_json_handler(payload))
    try:
        parsed = RemoteCoreClient(url, _TOKEN).list_catalog_dishes()
        assert parsed["dishes"][0]["dish_id"] == dish_id
    finally:
        server.shutdown()
        server.server_close()


def test_catalog_dish_detail_accepts_valid_payload() -> None:
    dish_id = str(uuid.uuid4())
    payload = {
        "dish_id": dish_id,
        "name": "Fingerfood",
        "current_unit_net_cents": 290,
        "price_display": "2,90 EUR",
        "allergens": ["A"],
        "allergen_labels": ["Gluten"],
        "active": True,
        "description": "Desc",
        "composition": "Comp",
        "notes": "Notes",
        "created_at": "2026-07-14T10:00:00+02:00",
        "updated_at": "2026-07-14T10:00:00+02:00",
        "price_history": [],
    }
    url, server = _serve(_json_handler(payload))
    try:
        parsed = RemoteCoreClient(url, _TOKEN).catalog_dish_detail(dish_id)
        assert parsed is not None
        assert parsed["dish_id"] == dish_id
    finally:
        server.shutdown()
        server.server_close()


def test_list_allergen_codes_accepts_valid_payload() -> None:
    payload = {"allergen_codes": [{"code": "A", "label": "Gluten"}]}
    url, server = _serve(_json_handler(payload))
    try:
        parsed = RemoteCoreClient(url, _TOKEN).list_allergen_codes()
        assert parsed["allergen_codes"][0]["code"] == "A"
    finally:
        server.shutdown()
        server.server_close()


def test_list_contacts_rejects_unknown_identity_source() -> None:
    payload = {
        "contacts": [
            {
                "contact_key": "x",
                "identity_source": "unknown",
                "display_name": "Example",
                "email": None,
                "phone": None,
                "inquiry_count": 0,
                "open_inquiries": 0,
                "active_orders": 0,
                "linked_order_count": 0,
                "contact_status": "interessent",
                "last_activity": "2026-07-14T10:00:00+02:00",
            }
        ]
    }
    url, server = _serve(_json_handler(payload))
    try:
        with pytest.raises(RemoteCoreError) as exc:
            RemoteCoreClient(url, _TOKEN).list_contacts()
        assert exc.value.code == "invalid_response"
    finally:
        server.shutdown()
        server.server_close()


def test_list_emails_accepts_valid_payload() -> None:
    inquiry_id = str(uuid.uuid4())
    payload = {
        "emails": [
            {
                "email_id": inquiry_id,
                "inquiry_id": inquiry_id,
                "contact_key": "inquiry:" + inquiry_id,
                "sender_name": "Example Contact",
                "sender_email": "customer@example.invalid",
                "subject": "Anfrage",
                "preview": "Preview",
                "crm_stage": "Neue Anfrage",
                "received_at": "2026-07-14T10:00:00+02:00",
                "external_ref": None,
                "linked_offer_id": None,
                "linked_order_ids": [],
            }
        ]
    }
    url, server = _serve(_json_handler(payload))
    try:
        parsed = RemoteCoreClient(url, _TOKEN).list_emails()
        assert parsed["emails"][0]["inquiry_id"] == inquiry_id
    finally:
        server.shutdown()
        server.server_close()


def test_email_detail_accepts_valid_payload() -> None:
    inquiry_id = str(uuid.uuid4())
    payload = {
        "email_id": inquiry_id,
        "inquiry_id": inquiry_id,
        "contact_key": "inquiry:" + inquiry_id,
        "sender_name": "Example Contact",
        "sender_email": "customer@example.invalid",
        "subject": "Anfrage",
        "preview": "Preview",
        "crm_stage": "Neue Anfrage",
        "received_at": "2026-07-14T10:00:00+02:00",
        "external_ref": None,
        "linked_offer_id": None,
        "linked_order_ids": [],
    }
    url, server = _serve(_json_handler(payload))
    try:
        parsed = RemoteCoreClient(url, _TOKEN).email_detail(inquiry_id)
        assert parsed is not None
        assert parsed["email_id"] == inquiry_id
    finally:
        server.shutdown()
        server.server_close()


def test_list_tasks_accepts_valid_payload() -> None:
    payload = {
        "tasks": [
            {
                "task_id": "task-1",
                "category": "verify",
                "title": "Rückruf",
                "subtitle": "Neue Anfrage",
                "entity_type": "inquiry",
                "entity_id": str(uuid.uuid4()),
                "action_label": "Öffnen",
                "action_href": "/office/anfragen/1",
                "due_at": "2026-07-20",
                "urgency": "normal",
                "opened_at": "2026-07-14T10:00:00+02:00",
            }
        ]
    }
    url, server = _serve(_json_handler(payload))
    try:
        parsed = RemoteCoreClient(url, _TOKEN).list_tasks()
        assert parsed["tasks"][0]["category"] == "verify"
    finally:
        server.shutdown()
        server.server_close()


def test_list_calendar_accepts_valid_payload() -> None:
    from datetime import date

    entity_id = str(uuid.uuid4())
    inquiry_id = str(uuid.uuid4())
    payload = {
        "entries": [
            {
                "entry_id": "cal-1",
                "entry_kind": "event_confirmed",
                "status_label": "Bestätigt",
                "title": "Event",
                "event_date": "2026-10-01",
                "time_window_text": "mittags",
                "location_text": "Hamburg",
                "guest_count_estimate": 25,
                "entity_type": "order",
                "entity_id": entity_id,
                "action_label": "Öffnen",
                "action_href": "/office/auftraege/1",
                "source_inquiry_id": inquiry_id,
            }
        ]
    }
    url, server = _serve(_json_handler(payload))
    try:
        parsed = RemoteCoreClient(url, _TOKEN).list_calendar(
            date(2026, 10, 1), date(2026, 10, 31)
        )
        assert parsed["entries"][0]["entry_kind"] == "event_confirmed"
    finally:
        server.shutdown()
        server.server_close()


def test_offer_detail_accepts_valid_payload() -> None:
    offer_id = str(uuid.uuid4())
    inquiry_id = str(uuid.uuid4())
    version_id = str(uuid.uuid4())
    variant_id = str(uuid.uuid4())
    position_id = str(uuid.uuid4())
    payload = {
        "offer_id": offer_id,
        "inquiry_id": inquiry_id,
        "offer_version_id": version_id,
        "commercial_state": "Prepared",
        "acceptance_id": None,
        "sent_evidence": None,
        "acceptance": None,
        "history": [{"at": "2026-07-14T10:00:00+02:00", "label": "Prepared"}],
        "versions": [
            {
                "version": 1,
                "state": "Prepared",
                "event_date": "2026-10-01",
                "valid_until": "2026-10-15",
                "time_window_text": "mittags",
                "location_text": "Hamburg",
                "guest_count": 25,
                "planning_mode": "caterer_suggestion",
                "variants": [
                    {
                        "variant_id": variant_id,
                        "name": "Variante A",
                        "positions": [
                            {
                                "position_id": position_id,
                                "kind": "catalog",
                                "name": "Fingerfood",
                                "unit_net_cents": 290,
                                "net_total_cents": 23200,
                                "catalog_item_id": None,
                                "description": None,
                                "composition": None,
                                "allergens": None,
                                "allergen_labels": None,
                                "allergens_unknown": False,
                            }
                        ],
                    }
                ],
            }
        ],
    }
    url, server = _serve(_json_handler(payload))
    try:
        parsed = RemoteCoreClient(url, _TOKEN).offer_detail(offer_id)
        assert parsed is not None
        assert parsed["offer_id"] == offer_id
    finally:
        server.shutdown()
        server.server_close()


def test_contact_detail_accepts_valid_payload() -> None:
    inquiry_id = str(uuid.uuid4())
    contact_key = "inquiry:" + inquiry_id
    payload = {
        "contact_key": contact_key,
        "identity_source": "inquiry",
        "display_name": "Example Contact",
        "email": "customer@example.invalid",
        "phone": None,
        "inquiry_count": 1,
        "open_inquiries": 1,
        "active_orders": 0,
        "linked_order_count": 0,
        "contact_status": "interessent",
        "last_activity": "2026-07-14T10:00:00+02:00",
        "inquiry_ids": [inquiry_id],
        "inquiries": [
            {
                "inquiry_id": inquiry_id,
                "intake_subject": "Anfrage",
                "event_date": "2026-10-01",
                "crm_stage": "Neue Anfrage",
                "is_open": True,
            }
        ],
        "offers": [],
        "orders": [],
    }
    url, server = _serve(_json_handler(payload))
    try:
        parsed = RemoteCoreClient(url, _TOKEN).contact_detail(contact_key)
        assert parsed is not None
        assert parsed["contact_key"] == contact_key
    finally:
        server.shutdown()
        server.server_close()
