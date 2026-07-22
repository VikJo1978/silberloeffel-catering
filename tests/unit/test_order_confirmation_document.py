"""EMAIL_MVP_1 — frozen Auftragsbestätigung document snapshot (Slice B1)."""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from catering_system.domain.offer import OfferPosition
from catering_system.repositories.in_memory_inquiry_repository import (
    InMemoryInquiryRepository,
)
from catering_system.repositories.in_memory_offer_repository import (
    InMemoryOfferRepository,
)
from catering_system.repositories.in_memory_order_confirmation_document_repository import (
    InMemoryOrderConfirmationDocumentRepository,
)
from catering_system.repositories.in_memory_order_repository import (
    InMemoryOrderRepository,
)
from catering_system.repositories.sqlite_order_confirmation_document_repository import (
    SQLiteOrderConfirmationDocumentRepository,
)
from catering_system.services.operational_core_service import OperationalCoreService
from catering_system.services.order_confirmation_document_hash import (
    compute_document_hash,
)
from catering_system.services.order_confirmation_document_service import (
    OrderConfirmationDocumentBlockedError,
    OrderConfirmationDocumentService,
    OrderConfirmationDocumentStaleVersionError,
    _commercial_positions,
)
from catering_system.services.order_service import OrderService
from catering_system.services.offer_service import OfferService
from catering_system.domain.order_payment_reminder import PaymentReminderView
from catering_system.domain.ready_to_send import ReadyToSendEvaluation
from catering_system.ui import office_api_views as views
from catering_system.ui.office_panel_order_detail import (
    OrderDetailFormFields,
    render_order_detail,
)
from catering_system.services.order_confirmation_outbound_service import (
    OutboundSendEligibility,
)
from tests.unit.test_offer_service import (
    _INQUIRY_ID,
    _POSITION_ID,
    _accepted_offer_state,
)


def _services() -> tuple[
    InMemoryOrderRepository,
    InMemoryOfferRepository,
    InMemoryInquiryRepository,
    InMemoryOrderConfirmationDocumentRepository,
    OrderConfirmationDocumentService,
    OperationalCoreService,
    OfferService,
]:
    (
        offer,
        version_id,
        variant_id,
        acceptance_id,
        offers,
        orders,
        inquiries,
        offer_service,
    ) = _accepted_offer_state()
    inquiry = inquiries.get_by_id(_INQUIRY_ID)
    assert inquiry is not None
    inquiries.update(
        replace(
            inquiry,
            intake_message="Firma: Example GmbH\nE-Mail: customer@example.invalid\n",
        )
    )
    _converted, order, order_version = offer_service.convert_accepted_offer(
        offer.offer_id,
        version_id,
        variant_id,
        acceptance_id,
    )
    core = OperationalCoreService(orders)
    core.confirm_kitchen_print(order.order_id, order_version.order_version_id)
    core.make_order_version_effective(order.order_id, order_version.order_version_id)
    documents = InMemoryOrderConfirmationDocumentRepository()
    service = OrderConfirmationDocumentService(
        orders,
        inquiries,
        documents,
        offer_service._commercial_snapshots,
        now=lambda: datetime(2026, 7, 18, 10, 0, tzinfo=UTC),
    )
    return orders, offers, inquiries, documents, service, core, offer_service


def _effective_order(
    services: tuple[object, ...],
) -> tuple[object, object]:
    orders, _offers, _inquiries, _documents, service, _core, _offer_service = services
    order = orders.list_orders()[0]
    version = orders.get_order_version(order.effective_order_version_id)
    assert version is not None
    return order, version


def test_snapshot_created_for_effective_order() -> None:
    services = _services()
    order, version = _effective_order(services)
    service = services[4]
    snapshot = service.prepare_snapshot(
        order.order_id,
        version.order_version_id,
        "office-panel",
    )
    assert snapshot.order_version_id == version.order_version_id
    assert snapshot.gross_total_cents == 24824
    assert snapshot.recipient_status == "ready"
    assert snapshot.document_hash.startswith("sha256:")


def test_no_effective_version_blocked() -> None:
    services = _services()
    orders, _offers, _inquiries, _documents, service, _core, _offer_service = services
    order = orders.list_orders()[0]
    orders.update_order(replace(order, effective_order_version_id=None))
    with pytest.raises(OrderConfirmationDocumentBlockedError, match="nicht_verfuegbar"):
        service.prepare_snapshot(order.order_id, str(uuid.uuid4()), "office-panel")


def test_pending_candidate_blocked() -> None:
    services = _services()
    orders, _offers, _inquiries, _documents, service, _core, offer_service = services
    order, version = _effective_order(services)
    offer_service  # silence lint
    OrderService(orders).propose_order_version_change(
        order.order_id,
        event_date=date(2026, 9, 1),
        time_window_text=version.time_window_text,
        location_text=version.location_text,
        guest_count_estimate=version.guest_count_estimate,
        planning_mode=version.planning_mode,
        actor_reference="office-panel",
        change_reason="Test",
    )
    with pytest.raises(OrderConfirmationDocumentBlockedError, match="aenderung_wartet"):
        service.prepare_snapshot(
            order.order_id,
            order.effective_order_version_id,
            "office-panel",
        )


def test_kitchen_print_not_confirmed_blocked() -> None:
    (
        offer,
        version_id,
        variant_id,
        acceptance_id,
        offers,
        orders,
        inquiries,
        offer_service,
    ) = _accepted_offer_state()
    _converted, order, order_version = offer_service.convert_accepted_offer(
        offer.offer_id,
        version_id,
        variant_id,
        acceptance_id,
    )
    orders.update_order(
        replace(order, effective_order_version_id=order_version.order_version_id)
    )
    service = OrderConfirmationDocumentService(
        orders,
        inquiries,
        InMemoryOrderConfirmationDocumentRepository(),
        offer_service._commercial_snapshots,
    )
    with pytest.raises(OrderConfirmationDocumentBlockedError, match="aenderung_wartet"):
        service.prepare_snapshot(
            order.order_id,
            order_version.order_version_id,
            "office-panel",
        )


def test_snapshot_uses_effective_order_version_facts() -> None:
    services = _services()
    order, version = _effective_order(services)
    service = services[4]
    snapshot = service.prepare_snapshot(
        order.order_id,
        version.order_version_id,
        "office-panel",
    )
    assert snapshot.event_date == version.event_date
    assert snapshot.location_text == "Hamburg"
    assert snapshot.guest_count_estimate == 80


def test_snapshot_uses_accepted_offer_positions() -> None:
    services = _services()
    order, version = _effective_order(services)
    service = services[4]
    snapshot = service.prepare_snapshot(
        order.order_id,
        version.order_version_id,
        "office-panel",
    )
    assert len(snapshot.positions) == 1
    assert snapshot.positions[0].name == "Fingerfood Paket"
    assert snapshot.positions[0].unit_net_cents == 290


def test_live_catalog_change_does_not_change_snapshot() -> None:
    services = _services()
    order, version = _effective_order(services)
    service = services[4]
    first = service.prepare_snapshot(
        order.order_id,
        version.order_version_id,
        "office-panel",
    )
    offers = services[1]
    stored_offer = offers.get_by_source_inquiry_id(order.source_inquiry_id)
    assert stored_offer is not None
    offer_version = stored_offer.versions[0]
    variant = offer_version.variants[0]
    mutated_position = replace(
        variant.positions[0],
        name="Live catalog mutation",
        unit_net_cents=999,
    )
    mutated_variant = replace(
        variant,
        positions=(mutated_position,),
    )
    mutated_version = replace(
        offer_version,
        variants=(mutated_variant,),
    )
    mutated_offer = replace(
        stored_offer,
        versions=(mutated_version,),
    )
    offers._offers[mutated_offer.offer_id] = mutated_offer
    second = service.prepare_snapshot(
        order.order_id,
        version.order_version_id,
        "office-panel",
    )
    assert second.document_snapshot_id == first.document_snapshot_id
    assert second.positions[0].name == "Fingerfood Paket"


def test_totals_and_vat_match_positions() -> None:
    services = _services()
    order, version = _effective_order(services)
    snapshot = services[4].prepare_snapshot(
        order.order_id,
        version.order_version_id,
        "office-panel",
    )
    net = sum(position.net_total_cents for position in snapshot.positions)
    vat = sum(position.vat_cents for position in snapshot.positions)
    gross = sum(position.gross_cents for position in snapshot.positions)
    assert (net, vat, gross) == (
        snapshot.net_total_cents,
        snapshot.vat_total_cents,
        snapshot.gross_total_cents,
    )


def test_surcharge_linkage_preserved() -> None:
    base_id = "88888888-8888-4888-8888-888888888881"
    surcharge_id = "99999999-9999-4999-8999-999999999991"
    base = OfferPosition(
        position_id=base_id,
        kind="catalog",
        name="Basis",
        unit_net_cents=1000,
        net_total_cents=1000,
        vat_rate_percent=7,
        vat_amount_cents=70,
        gross_total_cents=1070,
    )
    surcharge = OfferPosition(
        position_id=surcharge_id,
        kind="surcharge",
        name="Aufschlag",
        unit_net_cents=200,
        net_total_cents=200,
        vat_rate_percent=7,
        vat_amount_cents=14,
        gross_total_cents=214,
        related_position_id=base_id,
    )
    positions, _buckets, totals = _commercial_positions(
        (base, surcharge), guest_count_estimate=10
    )
    surcharge_position = next(item for item in positions if item.kind == "surcharge")
    assert surcharge_position.related_position_id == base_id
    assert totals["gross_total_cents"] == 1284


def test_fee_position_preserved() -> None:
    fee = OfferPosition(
        position_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        kind="fee",
        name="Servicepauschale",
        unit_net_cents=500,
        net_total_cents=500,
        vat_rate_percent=19,
        vat_amount_cents=95,
        gross_total_cents=595,
    )
    catalog = OfferPosition(
        position_id=_POSITION_ID,
        kind="catalog",
        name="Fingerfood Paket",
        unit_net_cents=290,
        net_total_cents=23200,
        vat_rate_percent=7,
        vat_amount_cents=1624,
        gross_total_cents=24824,
        quantity=Decimal("80"),
        quantity_mode="total",
        unit_label="Stück",
    )
    positions, _buckets, totals = _commercial_positions(
        (catalog, fee), guest_count_estimate=80
    )
    assert any(position.kind == "fee" for position in positions)
    assert totals["gross_total_cents"] == 25419


def test_recipient_snapshot_and_missing_email() -> None:
    (
        offer,
        version_id,
        variant_id,
        acceptance_id,
        offers,
        orders,
        inquiries,
        offer_service,
    ) = _accepted_offer_state()
    inquiry = inquiries.get_by_id(_INQUIRY_ID)
    assert inquiry is not None
    inquiries.update(
        replace(
            inquiry,
            intake_message="Firma: ACME GmbH\nName: Anna\nTelefon: +491701234567\n",
        )
    )
    _converted, order, order_version = offer_service.convert_accepted_offer(
        offer.offer_id,
        version_id,
        variant_id,
        acceptance_id,
    )
    core = OperationalCoreService(orders)
    core.confirm_kitchen_print(order.order_id, order_version.order_version_id)
    core.make_order_version_effective(order.order_id, order_version.order_version_id)
    service = OrderConfirmationDocumentService(
        orders,
        inquiries,
        InMemoryOrderConfirmationDocumentRepository(),
        offer_service._commercial_snapshots,
        now=lambda: datetime(2026, 7, 18, 10, 0, tzinfo=UTC),
    )
    snapshot = service.prepare_snapshot(
        order.order_id,
        order_version.order_version_id,
        "office-panel",
    )
    assert snapshot.recipient_status == "missing"
    assert snapshot.recipient_company == "ACME GmbH"
    assert snapshot.recipient_name == "Anna"
    assert snapshot.recipient_email is None


def test_document_hash_stable() -> None:
    services = _services()
    order, version = _effective_order(services)
    service = services[4]
    first = service.prepare_snapshot(
        order.order_id,
        version.order_version_id,
        "office-panel",
    )
    second = service.prepare_snapshot(
        order.order_id,
        version.order_version_id,
        "office-panel",
    )
    assert first.document_hash == second.document_hash
    assert first.document_hash == compute_document_hash(first)


def test_prepare_is_idempotent_per_order_version() -> None:
    services = _services()
    order, version = _effective_order(services)
    documents = services[3]
    service = services[4]
    first = service.prepare_snapshot(
        order.order_id,
        version.order_version_id,
        "office-panel",
    )
    second = service.prepare_snapshot(
        order.order_id,
        version.order_version_id,
        "office-panel",
    )
    assert first.document_snapshot_id == second.document_snapshot_id
    assert len(documents._by_id) == 1


def test_stale_expected_version_raises() -> None:
    services = _services()
    order, version = _effective_order(services)
    service = services[4]
    with pytest.raises(OrderConfirmationDocumentStaleVersionError):
        service.prepare_snapshot(order.order_id, str(uuid.uuid4()), "office-panel")


def test_new_effective_version_gets_new_snapshot() -> None:
    services = _services()
    orders, _offers, _inquiries, documents, service, core, _offer_service = services
    order, v1 = _effective_order(services)
    first = service.prepare_snapshot(
        order.order_id,
        v1.order_version_id,
        "office-panel",
    )
    v2 = OrderService(orders).propose_order_version_change(
        order.order_id,
        event_date=date(2026, 9, 2),
        time_window_text=v1.time_window_text,
        location_text="Kiel",
        guest_count_estimate=v1.guest_count_estimate,
        planning_mode=v1.planning_mode,
        actor_reference="office-panel",
        change_reason="Ort geändert",
    )
    core.confirm_kitchen_print(order.order_id, v2.order_version_id)
    core.make_order_version_effective(order.order_id, v2.order_version_id)
    second = service.prepare_snapshot(
        order.order_id,
        v2.order_version_id,
        "office-panel",
    )
    assert second.document_snapshot_id != first.document_snapshot_id
    assert second.location_text == "Kiel"
    stored_first = documents.get_by_id(first.document_snapshot_id)
    assert stored_first is not None
    assert stored_first.location_text == "Hamburg"


def test_sqlite_snapshot_is_immutable(tmp_path: Path) -> None:
    services = _services()
    order, version = _effective_order(services)
    snapshot = services[4].prepare_snapshot(
        order.order_id,
        version.order_version_id,
        "office-panel",
    )
    db = tmp_path / "core.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE orders (
            order_id TEXT PRIMARY KEY,
            source_inquiry_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            candidate_order_version_id TEXT,
            effective_order_version_id TEXT,
            cancelled_at TEXT
        );
        CREATE TABLE order_versions (
            order_version_id TEXT PRIMARY KEY,
            order_id TEXT NOT NULL,
            version_number INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            event_date TEXT NOT NULL,
            time_window_text TEXT NOT NULL,
            location_text TEXT NOT NULL,
            guest_count_estimate INTEGER,
            planning_mode TEXT NOT NULL,
            kitchen_print_confirmed_at TEXT
        );
        """
    )
    conn.execute(
        "INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            order.order_id,
            order.source_inquiry_id,
            order.created_at.isoformat(),
            order.updated_at.isoformat(),
            order.candidate_order_version_id,
            order.effective_order_version_id,
            None,
        ),
    )
    conn.execute(
        "INSERT INTO order_versions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            version.order_version_id,
            order.order_id,
            version.version_number,
            version.created_at.isoformat(),
            version.event_date.isoformat(),
            version.time_window_text,
            version.location_text,
            version.guest_count_estimate,
            version.planning_mode,
            version.kitchen_print_confirmed_at.isoformat()
            if version.kitchen_print_confirmed_at
            else None,
        ),
    )
    conn.commit()
    repo = SQLiteOrderConfirmationDocumentRepository.from_connection(conn)
    repo.insert(snapshot)
    with pytest.raises(sqlite3.Error, match="immutable"):
        conn.execute(
            "UPDATE order_confirmation_document_snapshots "
            "SET document_hash = ? WHERE document_snapshot_id = ?",
            ("sha256:" + ("b" * 64), snapshot.document_snapshot_id),
        )


def test_office_panel_confirmation_block_renders() -> None:
    services = _services()
    order, version = _effective_order(services)
    service = services[4]
    eligibility = service.eligibility(order.order_id)
    assert eligibility.state in {"bereit_zur_vorschau", "empfaenger_fehlt"}
    outbound = OutboundSendEligibility(state="dokument_fehlt", can_send=False)
    page = render_order_detail(
        order,
        services[0].list_order_versions(order.order_id),
        ReadyToSendEvaluation(order_id=order.order_id, ready=True, reasons=()),
        PaymentReminderView(
            order_id=order.order_id,
            payment_method=None,
            payment_method_label="Noch nicht gewählt",
            invoice_created=False,
            invoice_number=None,
            sent_on=None,
            due_on=None,
            paid_on=None,
            cash_received=False,
            invoice_state_label=None,
            payment_state_label="Offen",
            next_step="Zahlungsart wählen",
            updated_at=None,
        ),
        None,
        eligibility,
        outbound,
        forms=OrderDetailFormFields(
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
        versions_total_count=1,
        versions_truncated=False,
    )
    assert "Auftragsbestätigung" in page.body
    assert "Vorschau erstellen" in page.body
    snapshot = service.prepare_snapshot(
        order.order_id,
        version.order_version_id,
        "office-panel",
    )
    created = service.eligibility(order.order_id)
    outbound_created = OutboundSendEligibility(
        state="testversand_bereit",
        can_send=True,
    )
    page_created = render_order_detail(
        order,
        services[0].list_order_versions(order.order_id),
        ReadyToSendEvaluation(order_id=order.order_id, ready=True, reasons=()),
        PaymentReminderView(
            order_id=order.order_id,
            payment_method="RECHNUNG",
            payment_method_label="Rechnung",
            invoice_created=False,
            invoice_number=None,
            sent_on=None,
            due_on=None,
            paid_on=None,
            cash_received=False,
            invoice_state_label=None,
            payment_state_label="Offen",
            next_step="–",
            updated_at=datetime.now(UTC),
        ),
        None,
        created,
        outbound_created,
        forms=OrderDetailFormFields(
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
        versions_total_count=1,
        versions_truncated=False,
    )
    assert snapshot.document_reference in page_created.body
    assert "Vorschau öffnen" in page_created.body
    assert "Testversand erzeugen" in page_created.body
    assert views.confirmation_document_shape(created)["state"] == "dokument_erstellt"


def test_confirmation_uses_snapshot_when_offer_repository_unavailable() -> None:
    services = _services()
    order, version = _effective_order(services)
    orders, offers, _inquiries, _documents, service, _core, offer_service = services
    offers._offers.clear()

    snapshot = service.prepare_snapshot(
        order.order_id,
        version.order_version_id,
        "office-panel",
    )
    assert snapshot.gross_total_cents == 24824
    assert snapshot.payment_method == "RECHNUNG"
    assert snapshot.positions[0].name == "Fingerfood Paket"
    commercial = offer_service._commercial_snapshots.get_by_order_id(order.order_id)
    assert commercial is not None
    assert snapshot.offer_id == commercial.source_offer_id


def test_confirmation_snapshot_immune_to_later_offer_mutation() -> None:
    services = _services()
    order, version = _effective_order(services)
    orders, offers, inquiries, documents, _service, _core, offer_service = services
    commercial = offer_service._commercial_snapshots.get_by_order_id(order.order_id)
    assert commercial is not None
    stored = offers.get(commercial.source_offer_id)
    assert stored is not None
    offer_version = stored.versions[0]
    variant = offer_version.variants[0]
    offers._offers[stored.offer_id] = replace(
        stored,
        versions=(
            replace(
                offer_version,
                variants=(
                    replace(
                        variant,
                        positions=(
                            replace(variant.positions[0], name="MUTATED LIVE OFFER"),
                        ),
                    ),
                ),
            ),
        ),
    )
    service = OrderConfirmationDocumentService(
        orders,
        inquiries,
        documents,
        offer_service._commercial_snapshots,
        now=lambda: datetime(2026, 7, 18, 10, 0, tzinfo=UTC),
    )
    snapshot = service.prepare_snapshot(
        order.order_id,
        version.order_version_id,
        "office-panel",
    )
    assert snapshot.positions[0].name == "Fingerfood Paket"


def test_confirmation_fails_when_commercial_snapshot_missing() -> None:
    services = _services()
    order, version = _effective_order(services)
    orders, _offers, inquiries, documents, _service, _core, offer_service = services
    snapshots = offer_service._commercial_snapshots
    assert snapshots.get_by_order_id(order.order_id) is not None
    snapshots._by_id.clear()
    snapshots._by_order_id.clear()
    service = OrderConfirmationDocumentService(
        orders,
        inquiries,
        documents,
        snapshots,
        now=lambda: datetime(2026, 7, 18, 10, 0, tzinfo=UTC),
    )
    with pytest.raises(OrderConfirmationDocumentBlockedError, match="nicht_verfuegbar"):
        service.prepare_snapshot(
            order.order_id,
            version.order_version_id,
            "office-panel",
        )
