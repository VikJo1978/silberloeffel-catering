"""FULFILLMENT_SOURCE_V1 — acceptance suite (categories A-L + negatives).

Inquiry.fulfillment_mode (UNKNOWN|DELIVERY|PICKUP) is a top-level, structured
fact — never inferred from address, intake text, contact notes, or payment
method. UNKNOWN never blocks Inquiry->Order conversion; it blocks only
confirmation-document creation. DELIVERY requires an effective delivery
address; PICKUP never requires one and never disturbs stored address data.
Confirmation snapshots move to schema 3, which requires fulfillment_mode to
be DELIVERY or PICKUP (never UNKNOWN/null); schema 1/2 keep it NOT_STORED
forever.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from catering_system.domain.customer_document_eligibility import (
    CustomerDocumentCreationBlocked,
)
from catering_system.domain.customer_document_projection import CustomerAddress
from catering_system.domain.inquiry import (
    FULFILLMENT_MODES,
    Inquiry,
    validate_fulfillment_mode,
)
from catering_system.domain.inquiry_customer_snapshot import InquiryCustomerSnapshot
from catering_system.domain.order_commercial_snapshot import (
    OrderCommercialPosition,
    OrderCommercialSnapshot,
)
from catering_system.domain.order_confirmation_document import (
    SCHEMA_VERSION_V1,
    SCHEMA_VERSION_V2,
    SCHEMA_VERSION_V3,
    OrderConfirmationDocumentSnapshot,
)
from catering_system.intake.email_adapter import intake_from_email
from catering_system.intake.manual_adapter import intake_from_manual
from catering_system.intake.phone_adapter import intake_from_phone
from catering_system.intake.website_form_adapter import intake_from_website_form
from catering_system.intake.wix_form_adapter import intake_from_wix_form
from catering_system.repositories.in_memory_inquiry_repository import (
    InMemoryInquiryRepository,
)
from catering_system.repositories.in_memory_order_commercial_snapshot_repository import (
    InMemoryOrderCommercialSnapshotRepository,
)
from catering_system.repositories.in_memory_order_confirmation_document_repository import (
    InMemoryOrderConfirmationDocumentRepository,
)
from catering_system.repositories.in_memory_order_repository import (
    InMemoryOrderRepository,
)
from catering_system.repositories.sqlite_inquiry_repository import (
    SQLiteInquiryRepository,
)
from catering_system.services.inquiry_service import InquiryService
from catering_system.services.operational_core_service import OperationalCoreService
from catering_system.services.order_confirmation_document_hash import (
    compute_document_hash,
)
from catering_system.services.order_confirmation_document_serialization import (
    snapshot_from_canonical_json,
    snapshot_to_canonical_json,
)
from catering_system.services.order_confirmation_document_service import (
    OrderConfirmationDocumentService,
)
from catering_system.services.order_service import OrderService
from tests.helpers.order_seed import seed_order

_NOW = datetime(2026, 7, 18, 10, 0, tzinfo=UTC)
_INVOICE = CustomerAddress(
    street="Bürostraße 1", postal_code="20095", city="Hamburg", country="DE"
)
_DELIVERY = CustomerAddress(
    street="Eventplatz 9", postal_code="20457", city="Hamburg", country="DE"
)


def _commercial(order_id: str) -> OrderCommercialSnapshot:
    return OrderCommercialSnapshot(
        snapshot_id=str(uuid.uuid4()),
        order_id=order_id,
        source_offer_id=str(uuid.uuid4()),
        source_offer_version_id=str(uuid.uuid4()),
        source_variant_id=str(uuid.uuid4()),
        acceptance_id=str(uuid.uuid4()),
        accepted_at=_NOW,
        recorded_by="office-panel",
        variant_label="Variante A",
        payment_method="RECHNUNG",
        payment_customer_visible_text="Zahlung per Rechnung",
        created_at=_NOW,
        positions=(
            OrderCommercialPosition(
                position_id=str(uuid.uuid4()),
                kind="catalog",
                name="Fingerfood Paket",
                unit_net_cents=290,
                net_total_cents=23200,
                vat_rate_percent=7,
                vat_amount_cents=1624,
                gross_total_cents=24824,
                quantity=Decimal(80),
                quantity_mode="total",
                unit_label="Stück",
            ),
        ),
    )


def _ready_world(
    *,
    fulfillment_mode: str = "UNKNOWN",
    invoice_address: CustomerAddress | None = None,
    delivery_address: CustomerAddress | None = None,
    delivery_address_mode: str = "UNKNOWN",
    contact_complete: bool = True,
):
    """Inquiry + Order (kitchen-printed, effective) + commercial snapshot,
    ready for OrderConfirmationDocumentService.prepare_snapshot()."""
    inquiries = InMemoryInquiryRepository()
    orders = InMemoryOrderRepository()
    commercials = InMemoryOrderCommercialSnapshotRepository()
    documents = InMemoryOrderConfirmationDocumentRepository()

    snapshot = InquiryCustomerSnapshot(
        company_name="ACME GmbH",
        contact_name="Anna" if contact_complete else None,
        email="anna@example.invalid" if contact_complete else None,
        phone="+49301234567" if contact_complete else None,
        invoice_address=invoice_address,
        delivery_address=delivery_address,
        delivery_address_mode=delivery_address_mode,
    )
    inquiry = Inquiry(
        inquiry_id=str(uuid.uuid4()),
        event_date=date(2026, 8, 20),
        created_at=_NOW,
        updated_at=_NOW,
        inquiry_source="manual",
        crm_stage="Bestätigt / Auftrag",
        customer_linkage={},
        time_window_text="18:00–22:00",
        location_text="Hamburg",
        guest_count_estimate=40,
        planning_mode="caterer_suggestion",
        call_verification_required=False,
        call_verification_status="not_required",
        customer_snapshot=snapshot,
        fulfillment_mode=fulfillment_mode,
    )
    inquiries.save(inquiry)
    order, version = seed_order(orders, inquiry, created_at=_NOW)
    core = OperationalCoreService(orders)
    core.confirm_kitchen_print(order.order_id, version.order_version_id)
    core.make_order_version_effective(order.order_id, version.order_version_id)
    commercials.create(_commercial(order.order_id))
    doc_service = OrderConfirmationDocumentService(
        orders, inquiries, documents, commercials, now=lambda: _NOW
    )
    return inquiries, orders, documents, doc_service, order, version, inquiry


def _valid_schema3_snapshot(
    *, fulfillment_mode: object = "DELIVERY"
) -> OrderConfirmationDocumentSnapshot:
    return OrderConfirmationDocumentSnapshot(
        document_snapshot_id=str(uuid.uuid4()),
        order_id=str(uuid.uuid4()),
        order_version_id=str(uuid.uuid4()),
        offer_id=str(uuid.uuid4()),
        offer_version_id=str(uuid.uuid4()),
        document_reference="AB-2026-0001",
        created_at=_NOW,
        created_by="office-panel",
        recipient_name="Anna",
        recipient_email="anna@example.invalid",
        recipient_company="ACME GmbH",
        recipient_phone=None,
        recipient_status="ready",
        event_date=date(2026, 8, 20),
        time_window_text="18:00–22:00",
        location_text="Hamburg",
        guest_count_estimate=40,
        planning_mode="caterer_suggestion",
        positions=(),
        vat_buckets=(),
        net_total_cents=23200,
        vat_total_cents=1624,
        gross_total_cents=24824,
        payment_method="RECHNUNG",
        payment_customer_visible_text="Zahlung per Rechnung",
        document_hash="sha256:" + "0" * 64,
        schema_version=SCHEMA_VERSION_V3,
        invoice_address=None,
        delivery_address=None,
        delivery_address_differs=False,
        fulfillment_mode=fulfillment_mode,  # type: ignore[arg-type]
    )


# --- A: UNKNOWN storage -----------------------------------------------------


def test_a1_new_inquiry_defaults_to_unknown() -> None:
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    inquiry = svc.create_inquiry(
        event_date=date(2026, 8, 20),
        inquiry_source="manual",
        crm_stage="Neue Anfrage",
        customer_linkage={},
        time_window_text="18:00",
        location_text="Hamburg",
        guest_count_estimate=10,
        planning_mode="caterer_suggestion",
        call_verification_required=False,
        call_verification_status="not_required",
    )
    assert inquiry.fulfillment_mode == "UNKNOWN"


def test_a2_sqlite_round_trip_persists_default_unknown(tmp_path: Path) -> None:
    repo = SQLiteInquiryRepository(tmp_path / "core.db")
    svc = InquiryService(repo)
    created = svc.create_inquiry(
        event_date=date(2026, 8, 20),
        inquiry_source="manual",
        crm_stage="Neue Anfrage",
        customer_linkage={},
        time_window_text="18:00",
        location_text="Hamburg",
        guest_count_estimate=10,
        planning_mode="caterer_suggestion",
        call_verification_required=False,
        call_verification_status="not_required",
    )
    repo.close()
    reopened = SQLiteInquiryRepository(tmp_path / "core.db")
    loaded = reopened.get_by_id(created.inquiry_id)
    reopened.close()
    assert loaded is not None
    assert loaded.fulfillment_mode == "UNKNOWN"


def test_a3_sqlite_round_trip_persists_explicit_modes(tmp_path: Path) -> None:
    repo = SQLiteInquiryRepository(tmp_path / "core.db")
    svc = InquiryService(repo)
    for mode in ("DELIVERY", "PICKUP"):
        created = svc.create_inquiry(
            event_date=date(2026, 8, 20),
            inquiry_source="manual",
            crm_stage="Neue Anfrage",
            customer_linkage={},
            time_window_text="18:00",
            location_text="Hamburg",
            guest_count_estimate=10,
            planning_mode="caterer_suggestion",
            call_verification_required=False,
            call_verification_status="not_required",
            fulfillment_mode=mode,
        )
        loaded = repo.get_by_id(created.inquiry_id)
        assert loaded is not None
        assert loaded.fulfillment_mode == mode
    repo.close()


def test_a4_migration_backfills_existing_rows_to_unknown(tmp_path: Path) -> None:
    """Pre-existing rows (created before this migration ran) default to UNKNOWN."""
    from catering_system.repositories.sqlite_inquiry_repository import (
        _migration_6_add_fulfillment_mode,
    )

    db = tmp_path / "legacy.db"
    connection = sqlite3.connect(db)
    connection.execute("CREATE TABLE inquiries (inquiry_id TEXT PRIMARY KEY)")
    connection.execute("INSERT INTO inquiries (inquiry_id) VALUES ('legacy-row')")
    connection.commit()
    _migration_6_add_fulfillment_mode(connection)
    row = connection.execute(
        "SELECT fulfillment_mode FROM inquiries WHERE inquiry_id = 'legacy-row'"
    ).fetchone()
    connection.close()
    assert row is not None
    assert row[0] == "UNKNOWN"


def test_a5_service_setter_updates_and_is_idempotent() -> None:
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    inquiry = svc.create_inquiry(
        event_date=date(2026, 8, 20),
        inquiry_source="manual",
        crm_stage="Neue Anfrage",
        customer_linkage={},
        time_window_text="18:00",
        location_text="Hamburg",
        guest_count_estimate=10,
        planning_mode="caterer_suggestion",
        call_verification_required=False,
        call_verification_status="not_required",
    )
    first_updated_at = inquiry.updated_at
    changed = svc.set_inquiry_fulfillment_mode(
        inquiry.inquiry_id, fulfillment_mode="PICKUP"
    )
    assert changed.fulfillment_mode == "PICKUP"
    assert changed.updated_at >= first_updated_at
    unchanged = svc.set_inquiry_fulfillment_mode(
        inquiry.inquiry_id, fulfillment_mode="PICKUP"
    )
    assert unchanged.updated_at == changed.updated_at  # no-op: same value, no bump


# --- B: DELIVERY + SAME_AS_INVOICE -----------------------------------------


def test_b1_delivery_same_as_invoice_confirmation_created() -> None:
    _inquiries, _orders, documents, doc_service, order, version, _inq = _ready_world(
        fulfillment_mode="DELIVERY",
        invoice_address=_INVOICE,
        delivery_address_mode="SAME_AS_INVOICE",
    )
    snap = doc_service.prepare_snapshot(
        order.order_id, version.order_version_id, "office"
    )
    assert snap.fulfillment_mode == "DELIVERY"
    assert snap.delivery_address_differs is False
    assert documents.get_latest_for_order(order.order_id) is not None


# --- C: DELIVERY + SEPARATE --------------------------------------------------


def test_c1_delivery_separate_address_creates_document_with_warning() -> None:
    _inquiries, _orders, documents, doc_service, order, version, _inq = _ready_world(
        fulfillment_mode="DELIVERY",
        invoice_address=_INVOICE,
        delivery_address=_DELIVERY,
        delivery_address_mode="SEPARATE",
    )
    snap = doc_service.prepare_snapshot(
        order.order_id, version.order_version_id, "office"
    )
    assert snap.fulfillment_mode == "DELIVERY"
    assert snap.delivery_address_differs is True
    assert "DELIVERY_ADDRESS_DIFFERS_FROM_INVOICE" in snap.document_warnings
    assert documents.get_latest_for_order(order.order_id) is not None


# --- D: DELIVERY without an effective address is blocked --------------------


def test_d1_delivery_without_address_blocked_no_partial_document() -> None:
    _inquiries, _orders, documents, doc_service, order, version, _inq = _ready_world(
        fulfillment_mode="DELIVERY",
        delivery_address_mode="UNKNOWN",
    )
    with pytest.raises(CustomerDocumentCreationBlocked) as excinfo:
        doc_service.prepare_snapshot(order.order_id, version.order_version_id, "office")
    codes = tuple(b.code for b in excinfo.value.blockers)
    assert "DELIVERY_ADDRESS_REQUIRED_FOR_DELIVERY" in codes
    assert documents.get_latest_for_order(order.order_id) is None


# --- E: PICKUP ----------------------------------------------------------------


def test_e1_pickup_never_requires_address() -> None:
    _inquiries, _orders, _documents, doc_service, order, version, _inq = _ready_world(
        fulfillment_mode="PICKUP",
    )
    snap = doc_service.prepare_snapshot(
        order.order_id, version.order_version_id, "office"
    )
    assert snap.fulfillment_mode == "PICKUP"
    assert snap.delivery_address is None
    assert snap.delivery_address_differs is False


def test_e2_pickup_does_not_clear_existing_stored_address() -> None:
    inquiries, _orders, _documents, doc_service, order, version, inquiry = _ready_world(
        fulfillment_mode="PICKUP",
        invoice_address=_INVOICE,
        delivery_address=_DELIVERY,
        delivery_address_mode="SEPARATE",
    )
    doc_service.prepare_snapshot(order.order_id, version.order_version_id, "office")
    reloaded = inquiries.get_by_id(inquiry.inquiry_id)
    assert reloaded is not None
    assert reloaded.customer_snapshot is not None
    assert reloaded.customer_snapshot.delivery_address_mode == "SEPARATE"
    assert reloaded.customer_snapshot.delivery_address == _DELIVERY


def test_e3_pickup_suppresses_differs_warning_even_with_stored_addresses() -> None:
    _inquiries, _orders, _documents, doc_service, order, version, _inq = _ready_world(
        fulfillment_mode="PICKUP",
        invoice_address=_INVOICE,
        delivery_address=_DELIVERY,
        delivery_address_mode="SEPARATE",
    )
    snap = doc_service.prepare_snapshot(
        order.order_id, version.order_version_id, "office"
    )
    assert snap.delivery_address_differs is False
    assert "DELIVERY_ADDRESS_DIFFERS_FROM_INVOICE" not in snap.document_warnings


# --- F: UNKNOWN blocks confirmation but never conversion ---------------------


def test_f1_unknown_blocks_confirmation_document_creation() -> None:
    _inquiries, _orders, documents, doc_service, order, version, _inq = _ready_world(
        fulfillment_mode="UNKNOWN",
    )
    with pytest.raises(CustomerDocumentCreationBlocked) as excinfo:
        doc_service.prepare_snapshot(order.order_id, version.order_version_id, "office")
    codes = tuple(b.code for b in excinfo.value.blockers)
    assert "FULFILLMENT_MODE_REQUIRED" in codes
    assert documents.get_latest_for_order(order.order_id) is None


def test_f2_unknown_does_not_block_inquiry_to_order_conversion() -> None:
    inquiries = InMemoryInquiryRepository()
    orders = InMemoryOrderRepository()
    inquiry_svc = InquiryService(inquiries)
    order_svc = OrderService(orders)
    inquiry = inquiry_svc.create_inquiry(
        event_date=date(2026, 8, 20),
        inquiry_source="manual",
        crm_stage="Neue Anfrage",
        customer_linkage={},
        time_window_text="18:00",
        location_text="Hamburg",
        guest_count_estimate=10,
        planning_mode="caterer_suggestion",
        call_verification_required=False,
        call_verification_status="not_required",
    )
    assert inquiry.fulfillment_mode == "UNKNOWN"
    # Conversion (Order creation from an Inquiry with an accepted Offer)
    # never reads/reasons about fulfillment_mode: a linked Order can already
    # exist from a fully separate path, and the compatibility lookup does
    # not raise for an UNKNOWN-mode Inquiry.
    order, version = seed_order(orders, inquiry, created_at=_NOW)
    resolved_order, resolved_version = order_svc.convert_inquiry_to_order(inquiry)
    assert resolved_order.order_id == order.order_id
    assert resolved_version.order_version_id == version.order_version_id


# --- G: schema 3 invariants (immutability of the frozen contract) ----------


def test_g1_schema3_rejects_unknown_fulfillment_mode() -> None:
    with pytest.raises(ValueError, match="DELIVERY or PICKUP"):
        _valid_schema3_snapshot(fulfillment_mode="UNKNOWN")


def test_g2_schema3_rejects_none_fulfillment_mode() -> None:
    with pytest.raises(ValueError, match="DELIVERY or PICKUP"):
        _valid_schema3_snapshot(fulfillment_mode=None)


def test_g3_schema2_rejects_any_fulfillment_mode() -> None:
    with pytest.raises(ValueError, match="must not store fulfillment_mode"):
        OrderConfirmationDocumentSnapshot(
            **{
                **_valid_schema3_snapshot().__dict__,
                "schema_version": SCHEMA_VERSION_V2,
            }
        )


def test_g4_hash_differs_between_delivery_and_pickup() -> None:
    delivery = _valid_schema3_snapshot(fulfillment_mode="DELIVERY")
    pickup = _valid_schema3_snapshot(fulfillment_mode="PICKUP")
    assert compute_document_hash(delivery) != compute_document_hash(pickup)


# --- H: replay / immutability after later Inquiry changes -------------------


def test_h1_prepare_snapshot_is_idempotent_and_frozen_after_mode_change() -> None:
    inquiries, _orders, documents, doc_service, order, version, inquiry = _ready_world(
        fulfillment_mode="PICKUP",
    )
    first = doc_service.prepare_snapshot(
        order.order_id, version.order_version_id, "office"
    )
    replay = doc_service.prepare_snapshot(
        order.order_id, version.order_version_id, "office"
    )
    assert replay.document_snapshot_id == first.document_snapshot_id
    assert documents.get_latest_for_order(order.order_id) is not None
    # Changing the Inquiry's fulfillment_mode afterwards must not retroactively
    # change the already-persisted, frozen snapshot.
    inquiries.update(replace(inquiry, fulfillment_mode="DELIVERY"))
    still_same = doc_service.prepare_snapshot(
        order.order_id, version.order_version_id, "office"
    )
    assert still_same.fulfillment_mode == "PICKUP"
    assert still_same.document_snapshot_id == first.document_snapshot_id


# --- I: legacy schemas never gain the new fact ------------------------------


def test_i1_schema1_hash_and_json_unaffected_by_fulfillment_field() -> None:
    base = _valid_schema3_snapshot()
    legacy = OrderConfirmationDocumentSnapshot(
        **{
            **{k: v for k, v in base.__dict__.items() if k != "fulfillment_mode"},
            "schema_version": SCHEMA_VERSION_V1,
            "invoice_address": None,
            "delivery_address": None,
            "delivery_address_differs": None,
            "fulfillment_mode": None,
        }
    )
    assert legacy.fulfillment_mode is None
    assert legacy.fulfillment_fact_stored is False
    payload = json.loads(snapshot_to_canonical_json(legacy))
    assert "fulfillment_mode" not in payload


def test_i2_schema2_fulfillment_mode_is_always_none() -> None:
    base = _valid_schema3_snapshot()
    schema2 = OrderConfirmationDocumentSnapshot(
        **{
            **base.__dict__,
            "schema_version": SCHEMA_VERSION_V2,
            "fulfillment_mode": None,
        }
    )
    assert schema2.fulfillment_mode is None
    assert schema2.fulfillment_fact_stored is False
    payload = json.loads(snapshot_to_canonical_json(schema2))
    assert "fulfillment_mode" not in payload


def test_i3_schema3_full_round_trip_with_positions_and_warnings() -> None:
    """snapshot_to/from_canonical_json round-trips every field for a schema 3
    document with real positions, VAT buckets, and warnings (not just the
    happy-path empty fixture used elsewhere)."""
    from catering_system.domain.order_confirmation_document import (
        OrderConfirmationDocumentPosition,
        OrderConfirmationVatBucket,
    )

    snap = OrderConfirmationDocumentSnapshot(
        document_snapshot_id=str(uuid.uuid4()),
        order_id=str(uuid.uuid4()),
        order_version_id=str(uuid.uuid4()),
        offer_id=str(uuid.uuid4()),
        offer_version_id=str(uuid.uuid4()),
        document_reference="AB-2026-0002",
        created_at=_NOW,
        created_by="office-panel",
        recipient_name="Anna",
        recipient_email=None,
        recipient_company="ACME GmbH",
        recipient_phone="+49301234567",
        recipient_status="missing",
        event_date=date(2026, 8, 20),
        time_window_text="18:00–22:00",
        location_text="Hamburg",
        guest_count_estimate=40,
        planning_mode="caterer_suggestion",
        positions=(
            OrderConfirmationDocumentPosition(
                position_id=str(uuid.uuid4()),
                kind="catalog",
                name="Fingerfood Paket",
                unit_net_cents=290,
                net_total_cents=23200,
                vat_rate_percent=7,
                vat_cents=1624,
                gross_cents=24824,
                related_position_id=None,
                description="Kalt/Warm gemischt",
                composition="Lachs, Blini, Frischkäse",
                quantity="80 Stück",
                unit_label="Stück",
            ),
        ),
        vat_buckets=(
            OrderConfirmationVatBucket(
                rate_percent=7, base_net_cents=23200, vat_cents=1624
            ),
        ),
        net_total_cents=23200,
        vat_total_cents=1624,
        gross_total_cents=24824,
        payment_method="RECHNUNG",
        payment_customer_visible_text="Zahlung per Rechnung",
        document_hash="sha256:" + "1" * 64,
        schema_version=SCHEMA_VERSION_V3,
        document_warnings=("DELIVERY_ADDRESS_DIFFERS_FROM_INVOICE",),
        invoice_address=_INVOICE,
        delivery_address=_DELIVERY,
        delivery_address_differs=True,
        fulfillment_mode="DELIVERY",
    )
    reloaded = snapshot_from_canonical_json(snapshot_to_canonical_json(snap))
    assert reloaded == snap


# --- J: boundary — persisted preview path reads only the frozen snapshot ---


def test_j1_persisted_preview_modules_do_not_read_offer_or_inquiry() -> None:
    root = Path(__file__).resolve().parents[2] / "src" / "catering_system"
    text = (root / "services" / "order_confirmation_document_preview.py").read_text(
        encoding="utf-8"
    )
    assert "InquiryRepository" not in text
    assert "OfferRepository" not in text
    assert "inquiry_repository" not in text.lower()


def test_j2_persisted_preview_delivery_shows_label_and_frozen_address() -> None:
    """Review fix: order_confirmation_document_preview.py must read
    fulfillment_mode from the frozen snapshot, never from live Inquiry."""
    from catering_system.services.order_confirmation_document_preview import (
        build_preview,
        preview_to_json,
        render_preview_html,
    )

    _inquiries, _orders, _documents, doc_service, order, version, _inq = _ready_world(
        fulfillment_mode="DELIVERY",
        invoice_address=_INVOICE,
        delivery_address_mode="SAME_AS_INVOICE",
    )
    snapshot = doc_service.prepare_snapshot(
        order.order_id, version.order_version_id, "office"
    )
    preview = build_preview(snapshot)
    assert preview.fulfillment_facts_stored is True
    assert preview.fulfillment_mode == "DELIVERY"
    assert preview.fulfillment_label == "Lieferung"
    payload = preview_to_json(preview)
    assert payload["fulfillment_mode"] == "DELIVERY"
    html = render_preview_html(preview)
    assert "Lieferung" in html
    assert "Abholung" not in html
    assert "Bürostraße 1" in html


def test_j3_persisted_preview_pickup_hides_delivery_ui() -> None:
    from catering_system.services.order_confirmation_document_preview import (
        build_preview,
        preview_to_json,
        render_preview_html,
    )

    _inquiries, _orders, _documents, doc_service, order, version, _inq = _ready_world(
        fulfillment_mode="PICKUP",
        invoice_address=_INVOICE,
        delivery_address=_DELIVERY,
        delivery_address_mode="SEPARATE",
    )
    snapshot = doc_service.prepare_snapshot(
        order.order_id, version.order_version_id, "office"
    )
    preview = build_preview(snapshot)
    assert preview.fulfillment_facts_stored is True
    assert preview.fulfillment_mode == "PICKUP"
    assert preview.fulfillment_label == "Abholung"
    payload = preview_to_json(preview)
    assert payload["fulfillment_mode"] == "PICKUP"
    html = render_preview_html(preview)
    assert "Abholung" in html
    assert "Lieferung" not in html
    assert "Lieferadresse nicht festgelegt" not in html
    assert "DELIVERY_ADDRESS_DIFFERS_FROM_INVOICE" not in html
    assert "weicht ab" not in html
    # Rechnungsadresse continues to be shown for PICKUP.
    assert "Bürostraße 1" in html
    # The stored delivery address (Eventplatz 9) must not leak into a
    # document whose fulfillment mode says it is not applicable.
    assert "Eventplatz 9" not in html


def test_j4_persisted_preview_legacy_schema_has_no_live_fallback() -> None:
    from catering_system.services.order_confirmation_document_preview import (
        build_preview,
        preview_to_json,
        render_preview_html,
    )

    snap = _valid_schema3_snapshot(fulfillment_mode="DELIVERY")
    legacy = OrderConfirmationDocumentSnapshot(
        **{
            **snap.__dict__,
            "schema_version": SCHEMA_VERSION_V1,
            "invoice_address": None,
            "delivery_address": None,
            "delivery_address_differs": None,
            "fulfillment_mode": None,
        }
    )
    preview = build_preview(legacy)
    assert preview.fulfillment_facts_stored is False
    assert preview.fulfillment_mode is None
    payload = preview_to_json(preview)
    assert payload["fulfillment_mode"] is None
    assert payload["fulfillment_facts_stored"] is False
    html = render_preview_html(preview)
    assert "Lieferung" not in html
    assert "Abholung" not in html
    assert "nicht gespeichert" in html


def test_j5_persisted_preview_pickup_unaffected_by_later_inquiry_change() -> None:
    """Replay/immutability at the persisted-preview boundary, not just the
    snapshot object: mutating the live Inquiry after create must not change
    what a re-rendered persisted preview shows."""
    from catering_system.services.order_confirmation_document_preview import (
        build_preview,
        render_preview_html,
    )

    inquiries, _orders, _documents, doc_service, order, version, inquiry = _ready_world(
        fulfillment_mode="PICKUP"
    )
    snapshot = doc_service.prepare_snapshot(
        order.order_id, version.order_version_id, "office"
    )
    before = render_preview_html(build_preview(snapshot))
    inquiries.update(replace(inquiry, fulfillment_mode="DELIVERY"))
    replay = doc_service.prepare_snapshot(
        order.order_id, version.order_version_id, "office"
    )
    after = render_preview_html(build_preview(replay))
    assert before == after
    assert "Abholung" in after
    assert "Lieferung" not in after


# --- K: input channels — structured only, never inferred --------------------


def test_k1_manual_email_phone_wix_default_to_unknown() -> None:
    d = date(2026, 7, 15)
    for fn, raw in (
        (intake_from_manual, {"event_date": d}),
        (intake_from_email, {"event_date": d, "body_text": "b"}),
        (intake_from_phone, {"event_date": d}),
        (intake_from_wix_form, {"event_date": d}),
    ):
        repo = InMemoryInquiryRepository()
        svc = InquiryService(repo)
        q = fn(svc, raw)  # type: ignore[operator]
        assert q.fulfillment_mode == "UNKNOWN"


def test_k2_website_form_defaults_to_unknown() -> None:
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    q = intake_from_website_form(
        svc,
        {
            "event_date": date(2026, 7, 15),
            "email": "kunde@example.com",
            "phone": "030 123456",
        },
    )
    assert q.fulfillment_mode == "UNKNOWN"


def test_k3_manual_channel_accepts_explicit_structured_mode() -> None:
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    q = intake_from_manual(
        svc, {"event_date": date(2026, 7, 15), "fulfillment_mode": "PICKUP"}
    )
    assert q.fulfillment_mode == "PICKUP"


def test_k4_free_text_mentioning_lieferung_or_abholung_is_never_parsed() -> None:
    """Structured field absent -> UNKNOWN, even when intake text says otherwise."""
    repo = InMemoryInquiryRepository()
    svc = InquiryService(repo)
    q = intake_from_email(
        svc,
        {
            "event_date": date(2026, 7, 15),
            "subject": "Abholung gewünscht",
            "body_text": "Bitte um Lieferung morgen früh, keine Abholung möglich.",
        },
    )
    assert q.fulfillment_mode == "UNKNOWN"


# --- Negative tests ----------------------------------------------------------


def test_neg_office_api_rejects_invalid_fulfillment_mode(tmp_path: Path) -> None:
    from catering_system.repositories.core_transaction import open_core_connection
    from catering_system.ui.office_api import ApiError, OfficeApi

    api = OfficeApi(open_core_connection(tmp_path / "core.db"))
    inquiry = api.inquiry_service.create_inquiry(
        event_date=date(2026, 8, 20),
        inquiry_source="manual",
        crm_stage="Neue Anfrage",
        customer_linkage={},
        time_window_text="18:00",
        location_text="Hamburg",
        guest_count_estimate=10,
        planning_mode="caterer_suggestion",
        call_verification_required=False,
        call_verification_status="not_required",
    )
    with pytest.raises(ApiError) as excinfo:
        api.cmd_fulfillment_mode(
            {"id": inquiry.inquiry_id},
            {"fulfillment_mode": "BOGUS"},
            {"updated_at": inquiry.updated_at.isoformat()},
        )
    assert excinfo.value.status == 422
    assert excinfo.value.code == "invalid_fulfillment_mode"


def test_neg_invalid_db_value_raises_on_load(tmp_path: Path) -> None:
    db = tmp_path / "core.db"
    repo = SQLiteInquiryRepository(db)
    svc = InquiryService(repo)
    created = svc.create_inquiry(
        event_date=date(2026, 8, 20),
        inquiry_source="manual",
        crm_stage="Neue Anfrage",
        customer_linkage={},
        time_window_text="18:00",
        location_text="Hamburg",
        guest_count_estimate=10,
        planning_mode="caterer_suggestion",
        call_verification_required=False,
        call_verification_status="not_required",
    )
    repo.close()
    connection = sqlite3.connect(db)
    connection.execute(
        "UPDATE inquiries SET fulfillment_mode = 'BOGUS' WHERE inquiry_id = ?",
        (created.inquiry_id,),
    )
    connection.commit()
    connection.close()
    reopened = SQLiteInquiryRepository(db)
    with pytest.raises(ValueError):
        reopened.get_by_id(created.inquiry_id)
    reopened.close()


def test_neg_schema3_missing_fulfillment_mode_key_raises() -> None:
    snap = _valid_schema3_snapshot(fulfillment_mode="DELIVERY")
    payload = json.loads(snapshot_to_canonical_json(snap))
    del payload["fulfillment_mode"]
    with pytest.raises(ValueError, match="requires fulfillment_mode"):
        snapshot_from_canonical_json(json.dumps(payload))


def test_neg_schema3_null_fulfillment_mode_raises() -> None:
    snap = _valid_schema3_snapshot(fulfillment_mode="DELIVERY")
    payload = json.loads(snapshot_to_canonical_json(snap))
    payload["fulfillment_mode"] = None
    with pytest.raises(ValueError, match="DELIVERY or PICKUP"):
        snapshot_from_canonical_json(json.dumps(payload))


def test_neg_schema3_unknown_fulfillment_mode_value_raises() -> None:
    snap = _valid_schema3_snapshot(fulfillment_mode="DELIVERY")
    payload = json.loads(snapshot_to_canonical_json(snap))
    payload["fulfillment_mode"] = "UNKNOWN"
    with pytest.raises(ValueError, match="DELIVERY or PICKUP"):
        snapshot_from_canonical_json(json.dumps(payload))


def test_neg_unsupported_schema_version_raises() -> None:
    snap = _valid_schema3_snapshot(fulfillment_mode="DELIVERY")
    payload = json.loads(snapshot_to_canonical_json(snap))
    payload["schema_version"] = 4
    with pytest.raises(ValueError, match="unsupported"):
        snapshot_from_canonical_json(json.dumps(payload))


def test_neg_malformed_canonical_json_raises() -> None:
    with pytest.raises(json.JSONDecodeError):
        snapshot_from_canonical_json("{not valid json")


def test_neg_validate_fulfillment_mode_rejects_arbitrary_string() -> None:
    with pytest.raises(ValueError):
        validate_fulfillment_mode("ON_SITE_SERVICE")


def test_fulfillment_modes_are_exactly_the_contract_set() -> None:
    assert set(FULFILLMENT_MODES) == {"UNKNOWN", "DELIVERY", "PICKUP"}


# --- Office Panel: real HTTP form round trip ---------------------------------


def test_panel_http_fulfillment_mode_form_round_trip(tmp_path: Path) -> None:
    from tests.unit.test_customer_address_source_v1_b_panel import (
        _CSRF,
        _get,
        _post,
        _seed_order_world,
        _start_panel_server,
    )

    db, order_id, inquiry_id = _seed_order_world(tmp_path)
    base, server = _start_panel_server(db)
    try:
        status, page = _get(f"{base}/order/{order_id}")
        assert status == 200
        assert "Auftragsart" in page
        assert "Nicht festgelegt" in page
        status, _body = _post(
            f"{base}/inquiry/{inquiry_id}/fulfillment-mode",
            {
                "_csrf_token": _CSRF,
                "return_order_id": order_id,
                "fulfillment_mode": "PICKUP",
            },
        )
        assert status in {200, 302}
        status, page = _get(f"{base}/order/{order_id}")
        assert status == 200
        assert "Abholung" in page
    finally:
        server.shutdown()
        server.server_close()
