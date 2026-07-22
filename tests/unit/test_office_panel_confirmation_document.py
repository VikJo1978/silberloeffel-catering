"""Regression tests — B1 Auftragsbestätigung panel integration (legacy + wiring)."""

from __future__ import annotations

import base64
import queue
import sqlite3
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from http.server import HTTPServer
from pathlib import Path
from unittest.mock import patch

from catering_system.repositories.core_transaction import (
    CoreCommandExecutor,
    open_core_connection,
)
from catering_system.repositories.in_memory_order_confirmation_document_repository import (
    InMemoryOrderConfirmationDocumentRepository,
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
from catering_system.repositories.sqlite_order_repository import SQLiteOrderRepository
from catering_system.repositories.sqlite_payment_reminder_repository import (
    SQLitePaymentReminderRepository,
)
from catering_system.services.offer_service import OfferService
from catering_system.services.operational_core_service import OperationalCoreService
from catering_system.services.order_confirmation_document_service import (
    OrderConfirmationDocumentService,
)
from catering_system.services.order_service import OrderService
from catering_system.ui import office_api_views as views
from catering_system.ui.office_panel import OfficePanel, create_office_panel_server
from catering_system.ui.office_panel_http import csrf_token_for_password
from tests.unit.test_offer_service import (
    _INQUIRY_ID,
    _acceptance_args,
    _accepted_offer_state,
    _record_args,
    _sample_inquiry,
    _valid_snapshot,
)
from catering_system.ui.office_panel_order_detail import (
    OrderDetailFormFields,
    render_confirmation_card,
)

_PASSWORD = "panel-b1-pw"
_AUTH = "Basic " + base64.b64encode(f"office:{_PASSWORD}".encode()).decode()
_CSRF = csrf_token_for_password(_PASSWORD)


def _get(url: str, *, auth: bool = True) -> tuple[int, str, dict[str, str]]:
    req = urllib.request.Request(url)
    if auth:
        req.add_header("Authorization", _AUTH)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, resp.read().decode("utf-8"), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8"), dict(exc.headers)


def _post(url: str, fields: dict[str, str] | None = None) -> tuple[int, str]:
    body = urllib.parse.urlencode(fields or {}).encode()
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
        inquiry_repo = SQLiteInquiryRepository.from_connection(connection)
        order_repo = SQLiteOrderRepository.from_connection(connection)
        offer_repo = SQLiteOfferRepository.from_connection(connection)
        catalog_repo = SQLiteCatalogRepository.from_connection(connection)
        payment_reminder_repo = SQLitePaymentReminderRepository.from_connection(
            connection
        )
        confirmation_document_repo = (
            SQLiteOrderConfirmationDocumentRepository.from_connection(connection)
        )
        server = create_office_panel_server(
            inquiry_repo,
            order_repo,
            _PASSWORD,
            host="127.0.0.1",
            port=0,
            command_executor=CoreCommandExecutor(connection),
            payment_reminder_repo=payment_reminder_repo,
            confirmation_document_repo=confirmation_document_repo,
            offer_repo=offer_repo,
            catalog_repo=catalog_repo,
            ui_version=ui_version,
        )
        ready.put(server)
        server.serve_forever()

    threading.Thread(target=run, daemon=True).start()
    server = ready.get(timeout=5)
    host, port = server.server_address[:2]
    return f"http://{host}:{port}", server


def _sqlite_world(
    tmp_path: Path,
    *,
    intake_message: str = ("Firma: Example GmbH\nE-Mail: customer@example.invalid\n"),
) -> tuple[
    Path,
    OrderConfirmationDocumentService,
    OperationalCoreService,
    SQLiteOrderRepository,
    str,
    str,
]:
    db = tmp_path / "core.db"
    connection = open_core_connection(db)
    inquiries = SQLiteInquiryRepository.from_connection(connection)
    orders = SQLiteOrderRepository.from_connection(connection)
    offers = SQLiteOfferRepository.from_connection(connection)
    documents = SQLiteOrderConfirmationDocumentRepository.from_connection(connection)

    inquiry = replace(_sample_inquiry(), intake_message=intake_message)
    inquiries.save(inquiry)
    offer_service = OfferService(offers, inquiries, orders)
    offer = offer_service.prepare_offer_version(_INQUIRY_ID, _valid_snapshot())
    version_id = offer.versions[0].offer_version_id
    offer_service.record_sent_evidence(offer.offer_id, version_id, **_record_args())
    updated = offer_service.record_acceptance_evidence(
        offer.offer_id,
        version_id,
        "44444444-4444-4444-8444-444444444441",
        **_acceptance_args(),
    )
    assert updated.acceptance_evidence is not None
    converted, order, order_version = offer_service.convert_accepted_offer(
        offer.offer_id,
        version_id,
        "44444444-4444-4444-8444-444444444441",
        updated.acceptance_evidence.acceptance_id,
    )
    assert converted.conversion_link is not None
    core = OperationalCoreService(orders)
    core.confirm_kitchen_print(order.order_id, order_version.order_version_id)
    core.make_order_version_effective(order.order_id, order_version.order_version_id)
    doc_service = OrderConfirmationDocumentService(
        orders,
        offers,
        inquiries,
        documents,
        offer_service._commercial_snapshots,
        now=lambda: datetime(2026, 7, 18, 10, 0, tzinfo=UTC),
    )
    return db, doc_service, core, orders, order.order_id, order_version.order_version_id


def _snapshot_count(db: Path) -> int:
    conn = sqlite3.connect(db)
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM order_confirmation_document_snapshots"
        ).fetchone()[0]
    finally:
        conn.close()


def test_create_office_panel_server_passes_confirmation_document_repository() -> None:
    documents = InMemoryOrderConfirmationDocumentRepository()
    with patch(
        "catering_system.ui.office_panel_http.make_office_panel_handler"
    ) as make_handler:
        make_handler.return_value = object()
        create_office_panel_server(
            object(),
            object(),
            _PASSWORD,
            port=0,
            confirmation_document_repo=documents,
        )
    assert make_handler.call_args.kwargs["confirmation_document_repo"] is documents


def test_panel_handler_sees_sqlite_snapshot_created_outside_panel(
    tmp_path: Path,
) -> None:
    db, doc_service, _core, _orders, order_id, order_version_id = _sqlite_world(
        tmp_path
    )
    snapshot = doc_service.prepare_snapshot(
        order_id,
        order_version_id,
        "core-api-test",
    )
    panel_url, server = _start_panel_server(db)
    try:
        status, body, headers = _get(
            f"{panel_url}/order/{order_id}/confirmation-document/preview"
        )
        assert status == 200
        content_type = headers.get("Content-type") or headers.get("Content-Type", "")
        assert content_type.startswith("text/html")
        assert snapshot.document_reference in body
        assert "Auftragsbestätigung" in body
    finally:
        server.shutdown()
        server.server_close()


def test_legacy_order_detail_before_snapshot_shows_prepare_action(
    tmp_path: Path,
) -> None:
    db, doc_service, _core, _orders, order_id, _version_id = _sqlite_world(tmp_path)
    connection = open_core_connection(db)
    panel = OfficePanel(
        SQLiteInquiryRepository.from_connection(connection),
        SQLiteOrderRepository.from_connection(connection),
        confirmation_document_repo=SQLiteOrderConfirmationDocumentRepository.from_connection(
            connection
        ),
        offer_repo=SQLiteOfferRepository.from_connection(connection),
        ui_version="legacy",
    )
    eligibility = doc_service.eligibility(order_id)
    page = panel.render_order(order_id)
    assert page is not None
    assert "Auftragsbestätigung" in page
    assert views.confirmation_document_shape(eligibility)["state"] in {
        "bereit_zur_vorschau",
        "empfaenger_fehlt",
    }
    assert "Bereit zur Vorschau" in page or "Empfänger-E-Mail fehlt" in page
    assert "Vorschau erstellen" in page
    assert "Senden" not in page


def test_legacy_order_detail_after_snapshot_shows_created_facts(
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
    connection = open_core_connection(db)
    panel = OfficePanel(
        SQLiteInquiryRepository.from_connection(connection),
        SQLiteOrderRepository.from_connection(connection),
        confirmation_document_repo=SQLiteOrderConfirmationDocumentRepository.from_connection(
            connection
        ),
        offer_repo=SQLiteOfferRepository.from_connection(connection),
        ui_version="legacy",
    )
    page = panel.render_order(order_id)
    assert page is not None
    assert "Dokument erstellt" in page
    summary = doc_service.eligibility(order_id).snapshot
    assert summary is not None
    assert summary.recipient_email_masked is not None
    assert summary.recipient_email_masked.split("@")[-1] in page
    assert summary.document_hash_short.split(":")[0] in page
    assert snapshot.document_reference in page
    assert "Vorschau öffnen" in page
    assert "Senden" not in page


def test_legacy_panel_preview_route_returns_customer_facing_html(
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
        status, body, headers = _get(
            f"{panel_url}/order/{order_id}/confirmation-document/preview"
        )
        assert status == 200
        content_type = headers.get("Content-type") or headers.get("Content-Type", "")
        assert content_type.startswith("text/html")
        assert snapshot.document_reference in body
        assert "130,07" in body or "248,24" in body
    finally:
        server.shutdown()
        server.server_close()


def test_legacy_panel_preview_unknown_order_returns_404(tmp_path: Path) -> None:
    db, doc_service, _core, _orders, order_id, order_version_id = _sqlite_world(
        tmp_path
    )
    doc_service.prepare_snapshot(order_id, order_version_id, "office-panel")
    panel_url, server = _start_panel_server(db)
    try:
        status, _body, _headers = _get(
            f"{panel_url}/order/{uuid.uuid4()}/confirmation-document/preview"
        )
        assert status == 404
    finally:
        server.shutdown()
        server.server_close()


def test_panel_prepare_action_persists_single_snapshot(tmp_path: Path) -> None:
    db, _doc_service, _core, _orders, order_id, _version_id = _sqlite_world(tmp_path)
    panel_url, server = _start_panel_server(db)
    try:
        status, detail, _ = _get(f"{panel_url}/order/{order_id}")
        assert status == 200
        assert "Vorschau erstellen" in detail
        assert _snapshot_count(db) == 0

        status, _redirect = _post(
            f"{panel_url}/order/{order_id}/confirmation-document",
            {"_csrf_token": _CSRF},
        )
        assert status == 200
        assert _snapshot_count(db) == 1

        status, created, _ = _get(f"{panel_url}/order/{order_id}")
        assert status == 200
        assert "Dokument erstellt" in created
        assert "Vorschau erstellen" not in created

        status, _again = _post(
            f"{panel_url}/order/{order_id}/confirmation-document",
            {"_csrf_token": _CSRF},
        )
        assert status == 200
        assert _snapshot_count(db) == 1
    finally:
        server.shutdown()
        server.server_close()


def test_missing_email_shows_state_and_allows_preview(tmp_path: Path) -> None:
    db, doc_service, _core, _orders, order_id, order_version_id = _sqlite_world(
        tmp_path,
        intake_message="Firma: Ohne E-Mail GmbH\nName: Anna\n",
    )
    connection = open_core_connection(db)
    panel = OfficePanel(
        SQLiteInquiryRepository.from_connection(connection),
        SQLiteOrderRepository.from_connection(connection),
        confirmation_document_repo=SQLiteOrderConfirmationDocumentRepository.from_connection(
            connection
        ),
        offer_repo=SQLiteOfferRepository.from_connection(connection),
        ui_version="legacy",
    )
    before = panel.render_order(order_id)
    assert before is not None
    assert "Empfänger-E-Mail fehlt" in before

    snapshot = doc_service.prepare_snapshot(
        order_id,
        order_version_id,
        "office-panel",
    )
    assert snapshot.recipient_status == "missing"
    assert snapshot.recipient_email is None

    panel_url, server = _start_panel_server(db)
    try:
        status, preview, _headers = _get(
            f"{panel_url}/order/{order_id}/confirmation-document/preview"
        )
        assert status == 200
        assert "customer@example.invalid" not in preview
        assert "@example.invalid" not in preview
    finally:
        server.shutdown()
        server.server_close()


def test_pending_candidate_shows_blocked_state_without_prepare(tmp_path: Path) -> None:
    db, doc_service, _core, orders, order_id, _order_version_id = _sqlite_world(
        tmp_path
    )
    order = orders.get_order(order_id)
    assert order is not None
    effective = orders.get_order_version(order.effective_order_version_id)
    assert effective is not None
    OrderService(orders).propose_order_version_change(
        order_id,
        event_date=effective.event_date,
        time_window_text="abends",
        location_text="Pending City",
        guest_count_estimate=50,
        planning_mode="caterer_suggestion",
        actor_reference="office-panel",
        change_reason="Termin verschoben",
    )
    connection = open_core_connection(db)
    panel = OfficePanel(
        SQLiteInquiryRepository.from_connection(connection),
        SQLiteOrderRepository.from_connection(connection),
        confirmation_document_repo=SQLiteOrderConfirmationDocumentRepository.from_connection(
            connection
        ),
        offer_repo=SQLiteOfferRepository.from_connection(connection),
        ui_version="legacy",
    )
    page = panel.render_order(order_id)
    assert page is not None
    assert "Änderung wartet auf Küchendruck" in page
    assert "Vorschau erstellen" not in page
    assert doc_service.eligibility(order_id).can_prepare is False


def test_legacy_and_v2_share_confirmation_projection(tmp_path: Path) -> None:
    db, doc_service, _core, _orders, order_id, order_version_id = _sqlite_world(
        tmp_path
    )
    doc_service.prepare_snapshot(order_id, order_version_id, "office-panel")
    eligibility = doc_service.eligibility(order_id)
    assert eligibility.state == "dokument_erstellt"

    connection = open_core_connection(db)
    legacy = OfficePanel(
        SQLiteInquiryRepository.from_connection(connection),
        SQLiteOrderRepository.from_connection(connection),
        confirmation_document_repo=SQLiteOrderConfirmationDocumentRepository.from_connection(
            connection
        ),
        offer_repo=SQLiteOfferRepository.from_connection(connection),
        ui_version="legacy",
    )
    v2 = OfficePanel(
        SQLiteInquiryRepository.from_connection(connection),
        SQLiteOrderRepository.from_connection(connection),
        confirmation_document_repo=SQLiteOrderConfirmationDocumentRepository.from_connection(
            connection
        ),
        offer_repo=SQLiteOfferRepository.from_connection(connection),
        ui_version="v2",
    )
    legacy_page = legacy.render_order(order_id)
    v2_page = v2.render_order(order_id)
    assert legacy_page is not None and v2_page is not None
    assert "Dokument erstellt" in legacy_page
    assert "Dokument erstellt" in v2_page


def test_panel_preview_requires_basic_auth(tmp_path: Path) -> None:
    db, doc_service, _core, _orders, order_id, order_version_id = _sqlite_world(
        tmp_path
    )
    doc_service.prepare_snapshot(order_id, order_version_id, "office-panel")
    panel_url, server = _start_panel_server(db)
    try:
        status, _body, _headers = _get(
            f"{panel_url}/order/{order_id}/confirmation-document/preview",
            auth=False,
        )
        assert status == 401
    finally:
        server.shutdown()
        server.server_close()


def test_confirmation_card_escapes_hostile_user_data() -> None:
    services = _accepted_offer_state()
    (
        offer,
        version_id,
        variant_id,
        acceptance_id,
        offers,
        orders,
        inquiries,
        offer_service,
    ) = services
    inquiry = inquiries.get_by_id(_INQUIRY_ID)
    assert inquiry is not None
    inquiries.update(
        replace(
            inquiry,
            intake_message='Firma: <script>alert("x")</script>\nE-Mail: safe@example.invalid\n',
        )
    )
    updated, order, order_version = offer_service.convert_accepted_offer(
        offer.offer_id,
        version_id,
        variant_id,
        acceptance_id,
    )
    assert updated.conversion_link is not None
    core = OperationalCoreService(orders)
    core.confirm_kitchen_print(order.order_id, order_version.order_version_id)
    core.make_order_version_effective(order.order_id, order_version.order_version_id)
    documents = InMemoryOrderConfirmationDocumentRepository()
    doc_service = OrderConfirmationDocumentService(
        orders,
        offers,
        inquiries,
        documents,
        offer_service._commercial_snapshots,
        now=lambda: datetime(2026, 7, 18, 10, 0, tzinfo=UTC),
    )
    snapshot = doc_service.prepare_snapshot(
        order.order_id,
        order_version.order_version_id,
        "office-panel",
    )
    eligibility = doc_service.eligibility(order.order_id)
    card = render_confirmation_card(
        order,
        eligibility,
        forms=OrderDetailFormFields(
            csrf_input="",
            print_confirm_command_fields={},
            effective_command_fields={},
            ready_command_fields="",
            cancel_command_fields="",
            version_command_fields="",
            payment_command_fields="",
            confirmation_command_fields="",
        ),
    )
    assert snapshot.document_reference in card
    assert "<script>" not in card
    assert "alert(" not in card
