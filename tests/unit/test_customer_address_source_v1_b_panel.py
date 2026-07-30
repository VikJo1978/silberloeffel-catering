"""CUSTOMER_ADDRESS_SOURCE_V1-B — Order Detail facts + panel form (slices 3–4)."""

from __future__ import annotations

import base64
import queue
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import replace
from datetime import UTC, date, datetime
from http.server import HTTPServer
from pathlib import Path

from catering_system.domain.customer_document_projection import CustomerAddress
from catering_system.domain.inquiry_customer_snapshot import InquiryCustomerSnapshot
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
from catering_system.repositories.sqlite_order_commercial_snapshot_repository import (
    SQLiteOrderCommercialSnapshotRepository,
)
from catering_system.repositories.sqlite_order_confirmation_document_repository import (
    SQLiteOrderConfirmationDocumentRepository,
)
from catering_system.repositories.sqlite_order_repository import SQLiteOrderRepository
from catering_system.repositories.sqlite_payment_reminder_repository import (
    SQLitePaymentReminderRepository,
)
from catering_system.services.inquiry_service import InquiryService
from catering_system.services.offer_service import OfferService
from catering_system.services.operational_core_service import OperationalCoreService
from catering_system.ui.office_panel import OfficePanel, create_office_panel_server
from catering_system.ui.office_panel_http import csrf_token_for_password
from catering_system.ui.office_panel_order_detail import (
    OrderDetailFormFields,
    render_customer_addresses_card,
)
from tests.unit.test_offer_service import (
    _INQUIRY_ID,
    _acceptance_args,
    _record_args,
    _sample_inquiry,
    _valid_snapshot,
)

_PASSWORD = "panel-address-pw"
_AUTH = "Basic " + base64.b64encode(f"office:{_PASSWORD}".encode()).decode()
_CSRF = csrf_token_for_password(_PASSWORD)
_INVOICE = CustomerAddress(
    street="Bürostraße 1",
    postal_code="20095",
    city="Hamburg",
    country="DE",
)
_DELIVERY = CustomerAddress(
    street="Eventplatz 9",
    postal_code="20457",
    city="Hamburg",
    country="DE",
)


def _empty_forms(**overrides: object) -> OrderDetailFormFields:
    base: dict[str, object] = dict(
        csrf_input="",
        print_confirm_command_fields={},
        effective_command_fields={},
        ready_command_fields="",
        cancel_command_fields="",
        version_command_fields="",
        payment_command_fields="",
        customer_addresses_command_fields="",
    )
    base.update(overrides)
    return OrderDetailFormFields(**base)  # type: ignore[arg-type]


def test_address_card_separate_shows_stored_and_effective() -> None:
    inquiry = replace(
        _sample_inquiry(),
        customer_snapshot=InquiryCustomerSnapshot(
            company_name="ACME",
            email="a@b.de",
            phone="+49301",
            invoice_address=_INVOICE,
            delivery_address=_DELIVERY,
            delivery_address_mode="SEPARATE",
        ),
    )
    from catering_system.domain.order import Order

    order = Order(
        order_id="22222222-2222-4222-8222-222222222222",
        source_inquiry_id=inquiry.inquiry_id,
        created_at=datetime(2026, 7, 18, 10, 0, tzinfo=UTC),
        updated_at=datetime(2026, 7, 18, 10, 0, tzinfo=UTC),
    )
    card = render_customer_addresses_card(inquiry, order, _empty_forms())
    assert "Rechnungsadresse" in card
    assert "Bürostraße 1" in card
    assert "Abweichende Lieferadresse" in card
    assert "Gespeicherte Lieferadresse" in card
    assert "Eventplatz 9" in card
    assert "Effektive Lieferadresse" in card
    assert "Adressen bearbeiten" in card
    assert 'action="/inquiry/' in card
    assert "customer-addresses" in card
    assert 'name="return_order_id"' in card


def test_address_card_same_as_invoice_distinguishes_stored_vs_effective() -> None:
    inquiry = replace(
        _sample_inquiry(),
        customer_snapshot=InquiryCustomerSnapshot(
            company_name="ACME",
            email="a@b.de",
            phone="+49301",
            invoice_address=_INVOICE,
            delivery_address=None,
            delivery_address_mode="SAME_AS_INVOICE",
        ),
    )
    from catering_system.domain.order import Order

    order = Order(
        order_id="22222222-2222-4222-8222-222222222222",
        source_inquiry_id=inquiry.inquiry_id,
        created_at=datetime(2026, 7, 18, 10, 0, tzinfo=UTC),
        updated_at=datetime(2026, 7, 18, 10, 0, tzinfo=UTC),
    )
    card = render_customer_addresses_card(inquiry, order, _empty_forms())
    assert "Wie Rechnungsadresse" in card
    assert "keine separate Adresse" in card
    assert card.count("Bürostraße 1") >= 2
    assert "Eventplatz" not in card


def test_address_card_unknown_has_no_effective_delivery() -> None:
    inquiry = replace(
        _sample_inquiry(),
        customer_snapshot=InquiryCustomerSnapshot(
            company_name="ACME",
            email="a@b.de",
            phone="+49301",
            invoice_address=_INVOICE,
            delivery_address_mode="UNKNOWN",
        ),
    )
    from catering_system.domain.order import Order

    order = Order(
        order_id="22222222-2222-4222-8222-222222222222",
        source_inquiry_id=inquiry.inquiry_id,
        created_at=datetime(2026, 7, 18, 10, 0, tzinfo=UTC),
        updated_at=datetime(2026, 7, 18, 10, 0, tzinfo=UTC),
    )
    card = render_customer_addresses_card(inquiry, order, _empty_forms())
    assert "Unbekannt" in card
    assert "keine separate Adresse" in card
    assert "nicht festgelegt" in card
    assert "Bürostraße 1" in card


def _seed_order_world(tmp_path: Path) -> tuple[Path, str, str]:
    db = tmp_path / "core.db"
    connection = open_core_connection(db)
    inquiries = SQLiteInquiryRepository.from_connection(connection)
    orders = SQLiteOrderRepository.from_connection(connection)
    offers = SQLiteOfferRepository.from_connection(connection)
    commercial = SQLiteOrderCommercialSnapshotRepository.from_connection(connection)
    inquiry = replace(
        _sample_inquiry(),
        customer_snapshot=InquiryCustomerSnapshot(
            company_name="Example GmbH",
            email="customer@example.invalid",
            phone="+49301234567",
        ),
    )
    inquiries.save(inquiry)
    offer_service = OfferService(
        offers,
        inquiries,
        orders,
        commercial,
        today=lambda: date(2026, 7, 15),
    )
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
    _converted, order, order_version = offer_service.convert_accepted_offer(
        offer.offer_id,
        version_id,
        "44444444-4444-4444-8444-444444444441",
        updated.acceptance_evidence.acceptance_id,
    )
    core = OperationalCoreService(orders)
    core.confirm_kitchen_print(order.order_id, order_version.order_version_id)
    core.make_order_version_effective(order.order_id, order_version.order_version_id)
    connection.commit()
    connection.close()
    return db, order.order_id, inquiry.inquiry_id


def _panel(db: Path, *, ui_version: str = "v2") -> OfficePanel:
    connection = open_core_connection(db)
    inquiries = SQLiteInquiryRepository.from_connection(connection)
    orders = SQLiteOrderRepository.from_connection(connection)
    return OfficePanel(
        inquiries,
        orders,
        payment_reminder_repo=SQLitePaymentReminderRepository.from_connection(
            connection
        ),
        confirmation_document_repo=SQLiteOrderConfirmationDocumentRepository.from_connection(
            connection
        ),
        offer_repo=SQLiteOfferRepository.from_connection(connection),
        catalog_repo=SQLiteCatalogRepository.from_connection(connection),
        commercial_snapshot_repo=SQLiteOrderCommercialSnapshotRepository.from_connection(
            connection
        ),
        command_executor=CoreCommandExecutor(connection),
        ui_version=ui_version,
    )


def test_order_detail_shows_separate_addresses_after_service_write(
    tmp_path: Path,
) -> None:
    db, order_id, inquiry_id = _seed_order_world(tmp_path)
    panel = _panel(db)
    panel.inquiry_service.set_inquiry_customer_addresses(
        inquiry_id,
        invoice_address=_INVOICE,
        delivery_address=_DELIVERY,
        delivery_address_mode="SEPARATE",
    )
    page = panel.render_order(order_id)
    assert page is not None
    assert "Kundenadressen" in page
    assert "Bürostraße 1" in page
    assert "Eventplatz 9" in page
    assert "Abweichende Lieferadresse" in page
    assert 'action="/inquiry/' in page
    assert "customer-addresses" in page


def test_mode_changes_update_stored_and_effective_labels(tmp_path: Path) -> None:
    db, order_id, inquiry_id = _seed_order_world(tmp_path)
    panel = _panel(db)
    panel.inquiry_service.set_inquiry_customer_addresses(
        inquiry_id,
        invoice_address=_INVOICE,
        delivery_address=_DELIVERY,
        delivery_address_mode="SEPARATE",
    )
    panel.inquiry_service.set_inquiry_customer_addresses(
        inquiry_id,
        invoice_address=_INVOICE,
        delivery_address=_DELIVERY,
        delivery_address_mode="SAME_AS_INVOICE",
    )
    page = panel.render_order(order_id)
    assert page is not None
    assert "Wie Rechnungsadresse" in page
    assert "keine separate Adresse" in page
    assert "Eventplatz 9" not in page

    panel.inquiry_service.set_inquiry_customer_addresses(
        inquiry_id,
        invoice_address=_INVOICE,
        delivery_address=None,
        delivery_address_mode="UNKNOWN",
    )
    page = panel.render_order(order_id)
    assert page is not None
    assert "Unbekannt" in page
    assert "nicht festgelegt" in page


def test_contact_completion_after_address_form_preserves_addresses(
    tmp_path: Path,
) -> None:
    db, order_id, inquiry_id = _seed_order_world(tmp_path)
    panel = _panel(db)
    panel.inquiry_service.set_inquiry_customer_addresses(
        inquiry_id,
        invoice_address=_INVOICE,
        delivery_address=_DELIVERY,
        delivery_address_mode="SEPARATE",
    )
    inquiry = panel._inquiries.get_by_id(inquiry_id)
    assert inquiry is not None
    snap = inquiry.customer_snapshot
    assert snap is not None
    panel._inquiries.update(
        replace(
            inquiry,
            customer_snapshot=InquiryCustomerSnapshot(
                company_name=snap.company_name,
                contact_name=snap.contact_name,
                email=None,
                phone=snap.phone,
                invoice_address=snap.invoice_address,
                delivery_address=snap.delivery_address,
                delivery_address_mode=snap.delivery_address_mode,
            ),
        )
    )
    panel.complete_inquiry_contacts(
        inquiry_id, {"contact_email": "neu@example.invalid"}
    )
    page = panel.render_order(order_id)
    assert page is not None
    assert "Eventplatz 9" in page
    assert "Abweichende Lieferadresse" in page
    loaded = panel._inquiries.get_by_id(inquiry_id)
    assert loaded is not None
    assert loaded.customer_snapshot is not None
    assert loaded.customer_snapshot.email == "neu@example.invalid"
    assert loaded.customer_snapshot.delivery_address_mode == "SEPARATE"


def _start_panel_server(db: Path) -> tuple[str, HTTPServer]:
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
            confirmation_document_repo=(
                SQLiteOrderConfirmationDocumentRepository.from_connection(connection)
            ),
            offer_repo=SQLiteOfferRepository.from_connection(connection),
            catalog_repo=SQLiteCatalogRepository.from_connection(connection),
            commercial_snapshot_repo=SQLiteOrderCommercialSnapshotRepository.from_connection(
                connection
            ),
            ui_version="v2",
        )
        ready.put(server)
        server.serve_forever()

    threading.Thread(target=run, daemon=True).start()
    server = ready.get(timeout=5)
    host, port = server.server_address[:2]
    return f"http://{host}:{port}", server


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


def test_panel_http_customer_addresses_form_round_trip(tmp_path: Path) -> None:
    db, order_id, inquiry_id = _seed_order_world(tmp_path)
    base, server = _start_panel_server(db)
    try:
        status, page = _get(f"{base}/order/{order_id}")
        assert status == 200
        assert "Kundenadressen" in page
        assert "Adressen bearbeiten" in page
        status, _body = _post(
            f"{base}/inquiry/{inquiry_id}/customer-addresses",
            {
                "_csrf_token": _CSRF,
                "return_order_id": order_id,
                "delivery_address_mode": "SEPARATE",
                "invoice_street": _INVOICE.street or "",
                "invoice_postal_code": _INVOICE.postal_code or "",
                "invoice_city": _INVOICE.city or "",
                "invoice_country": _INVOICE.country or "",
                "delivery_street": _DELIVERY.street or "",
                "delivery_postal_code": _DELIVERY.postal_code or "",
                "delivery_city": _DELIVERY.city or "",
                "delivery_country": _DELIVERY.country or "",
            },
        )
        assert status in {200, 302}
        status, page = _get(f"{base}/order/{order_id}")
        assert status == 200
        assert "Eventplatz 9" in page
        assert "Abweichende Lieferadresse" in page
        assert "Bürostraße 1" in page
    finally:
        server.shutdown()
        server.server_close()


def test_legacy_and_v2_show_same_address_facts(tmp_path: Path) -> None:
    db, order_id, inquiry_id = _seed_order_world(tmp_path)
    connection = open_core_connection(db)
    inquiries = SQLiteInquiryRepository.from_connection(connection)
    service = InquiryService(inquiries)
    service.set_inquiry_customer_addresses(
        inquiry_id,
        invoice_address=_INVOICE,
        delivery_address=_DELIVERY,
        delivery_address_mode="SEPARATE",
    )
    connection.commit()
    v2 = _panel(db, ui_version="v2").render_order(order_id)
    legacy = _panel(db, ui_version="legacy").render_order(order_id)
    assert v2 is not None and legacy is not None
    for page in (v2, legacy):
        assert "Kundenadressen" in page
        assert "Bürostraße 1" in page
        assert "Eventplatz 9" in page
        assert "Abweichende Lieferadresse" in page
