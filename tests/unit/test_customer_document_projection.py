"""CUSTOMER_DOCUMENT_PROJECTION_FOUNDATION_V1 — pure projection builders."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from catering_system.domain.customer_document_projection import (
    WARNING_DELIVERY_ADDRESS_DIFFERS,
    CustomerAddress,
    CustomerDocumentRecipient,
)
from catering_system.domain.inquiry import Inquiry
from catering_system.domain.inquiry_customer_snapshot import InquiryCustomerSnapshot
from catering_system.domain.order import OrderVersion
from catering_system.domain.order_commercial_snapshot import (
    OrderCommercialPosition,
    OrderCommercialSnapshot,
)
from catering_system.services.customer_document_projection import (
    CustomerDocumentProjectionService,
    build_customer_document_projection,
    build_customer_document_recipient,
)

_ORDER_ID = "22222222-2222-4222-8222-222222222222"
_VERSION_ID = "33333333-3333-4333-8333-333333333331"
_SNAPSHOT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_OFFER_ID = "11111111-1111-4111-8111-111111111111"
_OFFER_VERSION_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
_POSITION_ID = "55555555-5555-4555-8555-555555555551"
_NOW = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)

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


def _inquiry(*, snapshot: InquiryCustomerSnapshot | None) -> Inquiry:
    return Inquiry(
        inquiry_id="99999999-9999-4999-8999-999999999999",
        event_date=date(2026, 8, 20),
        inquiry_source="manual",
        crm_stage="Bestätigt / Auftrag",
        customer_linkage={},
        created_at=_NOW,
        updated_at=_NOW,
        time_window_text="18:00–22:00",
        location_text="Hamburg",
        guest_count_estimate=80,
        planning_mode="caterer_suggestion",
        call_verification_required=False,
        call_verification_status="not_required",
        customer_snapshot=snapshot,
        intake_message="Firma: SHOULD-NOT-USE\nE-Mail: intake@example.invalid\n",
    )


def _order_version() -> OrderVersion:
    return OrderVersion(
        order_version_id=_VERSION_ID,
        order_id=_ORDER_ID,
        version_number=1,
        created_at=_NOW,
        event_date=date(2026, 8, 20),
        time_window_text="18:00–22:00",
        location_text="Hamburg",
        guest_count_estimate=80,
        planning_mode="caterer_suggestion",
    )


def _commercial_position() -> OrderCommercialPosition:
    return OrderCommercialPosition(
        position_id=_POSITION_ID,
        kind="catalog",
        name="Fingerfood Paket",
        unit_net_cents=290,
        net_total_cents=23200,
        vat_rate_percent=7,
        vat_amount_cents=1624,
        gross_total_cents=24824,
        description="Frozen description",
        composition="Frozen composition",
        quantity=Decimal("80"),
        quantity_mode="total",
        unit_label="Stück",
    )


def _commercial_snapshot() -> OrderCommercialSnapshot:
    return OrderCommercialSnapshot(
        snapshot_id=_SNAPSHOT_ID,
        order_id=_ORDER_ID,
        source_offer_id=_OFFER_ID,
        source_offer_version_id=_OFFER_VERSION_ID,
        source_variant_id="44444444-4444-4444-8444-444444444441",
        acceptance_id="66666666-6666-4666-8666-666666666661",
        accepted_at=_NOW,
        recorded_by="office-panel",
        variant_label="Variante A",
        payment_method="RECHNUNG",
        payment_customer_visible_text="Zahlung per Rechnung",
        created_at=_NOW,
        positions=(_commercial_position(),),
    )


def _projection(
    *,
    recipient: CustomerDocumentRecipient | None = None,
    commercial: OrderCommercialSnapshot | None = None,
    version: OrderVersion | None = None,
):
    return build_customer_document_projection(
        document_type="ORDER_CONFIRMATION",
        document_id="doc-1",
        created_at=_NOW,
        order_version=version or _order_version(),
        commercial_snapshot=commercial or _commercial_snapshot(),
        recipient=recipient
        or build_customer_document_recipient(
            _inquiry(
                snapshot=InquiryCustomerSnapshot(
                    contact_name="Anna",
                    email="anna@example.invalid",
                )
            )
        ),
    )


def test_same_invoice_and_delivery_address_has_no_warning() -> None:
    recipient = build_customer_document_recipient(
        _inquiry(snapshot=InquiryCustomerSnapshot(contact_name="Anna")),
        invoice_address=_INVOICE,
        delivery_address=_INVOICE,
    )
    assert recipient.delivery_address_differs is False
    assert recipient.warnings == ()
    projection = _projection(recipient=recipient)
    assert projection.recipient.warnings == ()


def test_different_invoice_and_delivery_address_emits_warning() -> None:
    recipient = build_customer_document_recipient(
        _inquiry(snapshot=InquiryCustomerSnapshot(contact_name="Anna")),
        invoice_address=_INVOICE,
        delivery_address=_DELIVERY,
    )
    assert recipient.delivery_address_differs is True
    assert WARNING_DELIVERY_ADDRESS_DIFFERS in recipient.warnings
    projection = _projection(recipient=recipient)
    assert WARNING_DELIVERY_ADDRESS_DIFFERS in projection.recipient.warnings


def test_delivery_missing_has_no_warning() -> None:
    recipient = build_customer_document_recipient(
        _inquiry(snapshot=InquiryCustomerSnapshot(contact_name="Anna")),
        invoice_address=_INVOICE,
        delivery_address=None,
    )
    assert recipient.delivery_address_differs is False
    assert recipient.warnings == ()


def test_both_addresses_missing_still_builds_projection() -> None:
    recipient = build_customer_document_recipient(
        _inquiry(snapshot=InquiryCustomerSnapshot(contact_name="Anna")),
    )
    assert recipient.invoice_address is None
    assert recipient.delivery_address is None
    assert recipient.delivery_address_differs is False
    assert recipient.warnings == ()
    projection = _projection(recipient=recipient)
    assert projection.document_type == "ORDER_CONFIRMATION"
    assert projection.recipient.email is None or projection.recipient.name == "Anna"


def test_commercial_reference_copied_from_snapshot() -> None:
    snapshot = _commercial_snapshot()
    projection = _projection(commercial=snapshot)
    assert projection.commercial_reference.snapshot_id == snapshot.snapshot_id
    assert projection.commercial_reference.source_offer_id == snapshot.source_offer_id
    assert (
        projection.commercial_reference.source_offer_version_id
        == snapshot.source_offer_version_id
    )
    assert projection.commercial_reference.variant_label == "Variante A"
    assert projection.payment_method == "RECHNUNG"
    assert projection.net_total_cents == 23200
    assert projection.vat_total_cents == 1624
    assert projection.gross_total_cents == 24824
    assert projection.positions[0].name == "Fingerfood Paket"
    assert projection.positions[0].kind == "catalog"
    assert projection.positions[0].quantity == "80 Stück"


def test_event_copied_from_order_version() -> None:
    version = _order_version()
    projection = _projection(version=version)
    assert projection.event.order_id == version.order_id
    assert projection.event.order_version_id == version.order_version_id
    assert projection.event.event_date == version.event_date
    assert projection.event.location_text == "Hamburg"
    assert projection.event.guest_count_estimate == 80
    assert projection.event.planning_mode == "caterer_suggestion"


def test_recipient_uses_customer_snapshot_not_intake_message() -> None:
    inquiry = _inquiry(
        snapshot=InquiryCustomerSnapshot(
            contact_name="Snapshot Name",
            email="snapshot@example.invalid",
        )
    )
    recipient = build_customer_document_recipient(inquiry)
    assert recipient.name == "Snapshot Name"
    assert recipient.email == "snapshot@example.invalid"
    assert "SHOULD-NOT-USE" not in recipient.name
    assert recipient.email != "intake@example.invalid"


def test_recipient_without_customer_snapshot_still_builds() -> None:
    recipient = build_customer_document_recipient(_inquiry(snapshot=None))
    assert recipient.name == "Kunde"
    assert recipient.email is None
    projection = _projection(recipient=recipient)
    assert projection.recipient.name == "Kunde"


def test_order_id_mismatch_raises() -> None:
    version = _order_version()
    commercial = _commercial_snapshot()
    from dataclasses import replace

    bad = replace(commercial, order_id="00000000-0000-4000-8000-000000000099")
    with pytest.raises(ValueError, match="order_id"):
        build_customer_document_projection(
            document_type="ORDER_CONFIRMATION",
            document_id="doc-1",
            created_at=_NOW,
            order_version=version,
            commercial_snapshot=bad,
            recipient=build_customer_document_recipient(
                _inquiry(snapshot=InquiryCustomerSnapshot(contact_name="Anna"))
            ),
        )


def test_customer_document_projection_service_build() -> None:
    service = CustomerDocumentProjectionService()
    projection = service.build(
        document_type="ORDER_CONFIRMATION",
        document_id="doc-1",
        created_at=_NOW,
        order_version=_order_version(),
        commercial_snapshot=_commercial_snapshot(),
        inquiry=_inquiry(
            snapshot=InquiryCustomerSnapshot(
                contact_name="Anna",
                email="anna@example.invalid",
            )
        ),
        invoice_address=_INVOICE,
        delivery_address=_DELIVERY,
    )
    assert WARNING_DELIVERY_ADDRESS_DIFFERS in projection.recipient.warnings
    assert projection.recipient.name == "Anna"
    assert projection.positions[0].kind == "catalog"


def test_recipient_maps_company_and_phone_from_customer_snapshot() -> None:
    recipient = build_customer_document_recipient(
        _inquiry(
            snapshot=InquiryCustomerSnapshot(
                contact_name="Anna",
                company_name="ACME GmbH",
                email="anna@example.invalid",
                phone="+49301234567",
            )
        )
    )
    assert recipient.name == "Anna"
    assert recipient.company_name == "ACME GmbH"
    assert recipient.phone == "+49301234567"
    assert recipient.email == "anna@example.invalid"


def test_foundation_modules_must_not_depend_on_offer_repository() -> None:
    root = Path(__file__).resolve().parents[2] / "src" / "catering_system"
    for relative in (
        "domain/customer_document_projection.py",
        "services/customer_document_projection.py",
    ):
        text = (root / relative).read_text(encoding="utf-8")
        assert "OfferRepository" not in text, relative
        assert "offer_repository" not in text, relative
        assert "conversion_link" not in text, relative
        assert "parse_intake_contact" not in text, relative
        assert "labelled_intake_context" not in text, relative
