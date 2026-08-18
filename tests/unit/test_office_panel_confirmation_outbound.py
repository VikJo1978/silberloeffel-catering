"""Regression tests — B2 fake outbox panel integration (legacy + v2)."""

from __future__ import annotations

import base64
import queue
import sqlite3
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from http.server import HTTPServer
from pathlib import Path

from catering_system.repositories.core_transaction import (
    CoreCommandExecutor,
    open_core_connection,
)
from catering_system.repositories.sqlite_catalog_repository import (
    SQLiteCatalogRepository,
)
from catering_system.repositories.sqlite_inquiry_repository import (
    SQLiteInquiryRepository,
)
from catering_system.repositories.sqlite_offer_repository import SQLiteOfferRepository
from catering_system.repositories.sqlite_order_confirmation_document_repository import (
    SQLiteOrderConfirmationDocumentRepository,
)
from catering_system.repositories.sqlite_order_confirmation_outbound_repository import (
    SQLiteOrderConfirmationOutboundRepository,
)
from catering_system.repositories.sqlite_order_repository import SQLiteOrderRepository
from catering_system.repositories.sqlite_payment_reminder_repository import (
    SQLitePaymentReminderRepository,
)
from catering_system.services.order_confirmation_outbound_service import (
    OrderConfirmationOutboundService,
)
from catering_system.ui.office_panel import OfficePanel, create_office_panel_server
from catering_system.ui.office_panel_http import csrf_token_for_password
from catering_system.ui.office_panel_order_detail import (
    OrderDetailFormFields,
    render_confirmation_outbound_card,
)
from tests.helpers.office_panel_context import legacy_office_context
from tests.unit.test_office_panel_confirmation_document import _sqlite_world

_PASSWORD = "panel-b2-pw"
_AUTH = "Basic " + base64.b64encode(f"office:{_PASSWORD}".encode()).decode()
_CSRF = csrf_token_for_password(_PASSWORD)


def _get(url: str) -> tuple[int, str]:
    req = urllib.request.Request(url)
    req.add_header("Authorization", _AUTH)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


def _post(url: str, fields: dict[str, str]) -> tuple[int, str]:
    body = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Authorization", _AUTH)
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


def _start_panel_server(
    db: Path, *, ui_version: str = "legacy"
) -> tuple[str, HTTPServer]:
    ready: queue.Queue[HTTPServer] = queue.Queue()

    def run() -> None:
        connection = open_core_connection(db)
        server = create_office_panel_server(
            SQLiteInquiryRepository.from_connection(connection),
            SQLiteOrderRepository.from_connection(connection),
            _PASSWORD,
            host="127.0.0.1",
            port=0,
            command_executor=CoreCommandExecutor(connection),
            payment_reminder_repo=SQLitePaymentReminderRepository.from_connection(
                connection
            ),
            confirmation_document_repo=SQLiteOrderConfirmationDocumentRepository.from_connection(
                connection
            ),
            confirmation_outbound_repo=SQLiteOrderConfirmationOutboundRepository.from_connection(
                connection
            ),
            offer_repo=SQLiteOfferRepository.from_connection(connection),
            catalog_repo=SQLiteCatalogRepository.from_connection(connection),
            ui_version=ui_version,
        )
        ready.put(server)
        server.serve_forever()

    threading.Thread(target=run, daemon=True).start()
    server = ready.get(timeout=5)
    host, port = server.server_address[:2]
    return f"http://{host}:{port}", server


def _evidence_count(db: Path) -> int:
    conn = sqlite3.connect(db)
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM order_confirmation_send_evidence"
        ).fetchone()[0]
    finally:
        conn.close()


def _panel_with_outbound(db: Path, *, ui_version: str = "legacy") -> OfficePanel:
    connection = open_core_connection(db)
    orders = SQLiteOrderRepository.from_connection(connection)
    offers = SQLiteOfferRepository.from_connection(connection)
    inquiries = SQLiteInquiryRepository.from_connection(connection)
    documents = SQLiteOrderConfirmationDocumentRepository.from_connection(connection)
    outbound = SQLiteOrderConfirmationOutboundRepository.from_connection(connection)
    return OfficePanel(
        inquiries,
        orders,
        confirmation_document_repo=documents,
        confirmation_outbound_repo=outbound,
        offer_repo=offers,
        command_executor=CoreCommandExecutor(connection),
        ui_version=ui_version,
    )


def test_outbound_card_before_send_shows_testversand_warning(tmp_path: Path) -> None:
    db, doc_service, _core, orders, order_id, order_version_id = _sqlite_world(tmp_path)
    snapshot = doc_service.prepare_snapshot(
        order_id,
        order_version_id,
        "office-panel",
    )
    panel = _panel_with_outbound(db)
    confirmation = doc_service.eligibility(order_id)
    outbound = panel.confirmation_outbound_service.send_eligibility(
        order_id,
        document_snapshot_id=snapshot.document_snapshot_id,
    )
    card = render_confirmation_outbound_card(
        orders.get_order(order_id),
        confirmation,
        outbound,
        OrderDetailFormFields(
            csrf_input="",
            print_confirm_command_fields={},
            effective_command_fields={},
            ready_command_fields="",
            cancel_command_fields="",
            version_command_fields="",
            payment_command_fields="",
            confirmation_command_fields="",
            send_command_fields="",
        ),
        context=legacy_office_context(),
    )
    assert "Testversand erzeugen" in card
    assert "Es wird keine E-Mail an den Kunden gesendet." in card
    assert "E-Mail gesendet" not in card


def test_legacy_order_detail_shows_outbound_block(tmp_path: Path) -> None:
    db, doc_service, _core, _orders, order_id, order_version_id = _sqlite_world(
        tmp_path
    )
    doc_service.prepare_snapshot(order_id, order_version_id, "office-panel")
    panel = _panel_with_outbound(db, ui_version="legacy")
    page = panel.render_order(order_id, context=legacy_office_context())
    assert page is not None
    assert "Testversand erzeugen" in page
    assert "Es wird keine E-Mail an den Kunden gesendet." in page
    assert "E-Mail gesendet" not in page


def test_panel_test_send_persists_evidence_and_shows_protokolliert(
    tmp_path: Path,
) -> None:
    db, doc_service, _core, _orders, order_id, order_version_id = _sqlite_world(
        tmp_path
    )
    snapshot = doc_service.prepare_snapshot(
        order_id,
        order_version_id,
        "office-panel",
    )
    panel_url, server = _start_panel_server(db)
    try:
        assert _evidence_count(db) == 0
        status, _body = _post(
            f"{panel_url}/order/{order_id}/confirmation-document/send",
            {
                "_csrf_token": _CSRF,
                "document_snapshot_id": snapshot.document_snapshot_id,
            },
        )
        assert status == 200
        assert _evidence_count(db) == 1

        status, page = _get(f"{panel_url}/order/{order_id}")
        assert status == 200
        assert "Testversand protokolliert" in page
        assert "Keine echte Zustellung" in page
        assert "Testnachricht ansehen" in page
        assert "E-Mail gesendet" not in page

        status, _again = _post(
            f"{panel_url}/order/{order_id}/confirmation-document/send",
            {
                "_csrf_token": _CSRF,
                "document_snapshot_id": snapshot.document_snapshot_id,
            },
        )
        assert status == 200
        assert _evidence_count(db) == 1
    finally:
        server.shutdown()
        server.server_close()


def test_fake_outbox_hidden_without_send_permission(tmp_path: Path) -> None:
    db, doc_service, _core, _orders, order_id, order_version_id = _sqlite_world(
        tmp_path,
        clear_recipient_email_after_convert=True,
    )
    doc_service.prepare_snapshot(order_id, order_version_id, "office-panel")
    panel = _panel_with_outbound(db)
    page = panel.render_order(order_id)
    assert page is not None
    assert "Fake Outbox" not in page
    assert "Empfänger-E-Mail fehlt" not in page
    assert "Testversand erzeugen" not in page


def test_fake_outbox_inspection_route_returns_payload(tmp_path: Path) -> None:
    db, doc_service, _core, _orders, order_id, order_version_id = _sqlite_world(
        tmp_path
    )
    snapshot = doc_service.prepare_snapshot(
        order_id,
        order_version_id,
        "office-panel",
    )
    connection = open_core_connection(db)
    orders = SQLiteOrderRepository.from_connection(connection)
    documents = SQLiteOrderConfirmationDocumentRepository.from_connection(connection)
    outbound = SQLiteOrderConfirmationOutboundRepository.from_connection(connection)
    from catering_system.services.operational_core_service import OperationalCoreService

    outbound_service = OrderConfirmationOutboundService(
        orders,
        documents,
        outbound,
        OperationalCoreService(orders),
        now=lambda: datetime(2026, 7, 18, 12, 0, tzinfo=UTC),
    )
    outbound_service.send_to_fake_outbox(
        order_id,
        snapshot.document_snapshot_id,
        order_version_id,
        "office-panel",
    )
    panel_url, server = _start_panel_server(db)
    try:
        status, body = _get(
            f"{panel_url}/order/{order_id}/confirmation-document/fake-outbox"
        )
        assert status == 200
        assert "Testtransport — keine echte Zustellung." in body
        assert snapshot.document_reference in body
    finally:
        server.shutdown()
        server.server_close()
