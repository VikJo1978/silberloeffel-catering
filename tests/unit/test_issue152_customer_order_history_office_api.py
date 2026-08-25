from __future__ import annotations

import json
import queue
import threading
import urllib.error
import urllib.request
from datetime import UTC, date, datetime
from http.server import HTTPServer
from pathlib import Path

import pytest

from catering_system.domain.customer_identity import CustomerIdentity
from catering_system.domain.inquiry import Inquiry
from catering_system.domain.order import Order, OrderVersion
from catering_system.repositories.sqlite_customer_identity_repository import (
    SQLiteCustomerIdentityRepository,
)
from catering_system.repositories.sqlite_inquiry_repository import SQLiteInquiryRepository
from catering_system.repositories.sqlite_order_repository import SQLiteOrderRepository
from tests.helpers.offer_pdf_static_content import fake_offer_pdf_static_content

_TOKEN = "test-office-api-token"
_AUTH = {"Authorization": f"Bearer {_TOKEN}"}
_NOW = datetime(2026, 8, 25, 17, 0, tzinfo=UTC)


def _seed(db: Path) -> None:
    customers = SQLiteCustomerIdentityRepository(db)
    customers.add(
        CustomerIdentity(
            customer_id="customer-1",
            display_name="Testkunde",
            company_name=None,
            status="active",
            created_at=_NOW,
            updated_at=_NOW,
        )
    )
    customers.close()

    inquiries = SQLiteInquiryRepository(db)
    inquiries.save(
        Inquiry(
            inquiry_id="inquiry-1",
            event_date=date(2026, 8, 20),
            created_at=_NOW,
            updated_at=_NOW,
            inquiry_source="manual",
            crm_stage="Bestätigt / Auftrag",
            customer_linkage={},
            time_window_text="18:00",
            location_text="Hamburg",
            guest_count_estimate=24,
            planning_mode="caterer_suggestion",
            call_verification_required=False,
            call_verification_status="not_required",
            customer_id="customer-1",
            fulfillment_mode="PICKUP",
        )
    )
    inquiries.close()

    orders = SQLiteOrderRepository(db)
    order = Order(
        order_id="order-1",
        source_inquiry_id="inquiry-1",
        created_at=_NOW,
        updated_at=_NOW,
    )
    version = OrderVersion(
        order_version_id="order-version-1",
        order_id="order-1",
        version_number=1,
        created_at=_NOW,
        event_date=date(2026, 8, 20),
        time_window_text="18:00",
        location_text="Hamburg",
        guest_count_estimate=24,
        planning_mode="caterer_suggestion",
    )
    orders.save_order_with_initial_version(order, version)
    orders.close()


def _start_server(db: Path) -> tuple[HTTPServer, threading.Thread, str]:
    ready: queue.Queue[HTTPServer] = queue.Queue()

    def run() -> None:
        from catering_system.ui.office_api import create_office_api_server

        server = create_office_api_server(
            str(db),
            _TOKEN,
            "127.0.0.1",
            0,
            offer_pdf_static_content=fake_offer_pdf_static_content(),
        )
        ready.put(server)
        server.serve_forever()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    server = ready.get(timeout=5)
    host, port = server.server_address[:2]
    return server, thread, f"http://{host}:{port}"


@pytest.fixture()
def history_api(tmp_path: Path):
    db = tmp_path / "core.db"
    _seed(db)
    server, thread, base = _start_server(db)
    try:
        yield base
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert thread.is_alive() is False


def _get(url: str) -> tuple[int, dict[str, object]]:
    request = urllib.request.Request(url, headers=_AUTH)
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode() or "{}")


def test_customer_order_history_is_exposed_as_read_only_fact_projection(
    history_api: str,
) -> None:
    status, body = _get(
        f"{history_api}/office/v1/customers/customer-1/order-history"
    )

    assert status == 200
    assert body["customer_id"] == "customer-1"
    history = body["orders"]
    assert isinstance(history, list)
    assert len(history) == 1
    order = history[0]
    assert isinstance(order, dict)
    assert order["order_id"] == "order-1"
    assert order["event_date"] == "2026-08-20"
    assert order["guest_count"] == 24
    assert order["fulfillment_mode"] == "PICKUP"
    assert order["accepted_offer_id"] is None
    assert order["dishes"] == []
    assert order["gross_total_cents"] is None


def test_missing_customer_order_history_is_404(history_api: str) -> None:
    status, body = _get(f"{history_api}/office/v1/customers/missing/order-history")

    assert status == 404
    assert body == {"error": "customer_not_found"}
