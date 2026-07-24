"""CUSTOMER_DOCUMENT_PROJECTION_V1-D — live confirmation preview."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from catering_system.domain.customer_document_projection import (
    WARNING_DELIVERY_ADDRESS_DIFFERS,
    CustomerAddress,
)
from catering_system.domain.inquiry import Inquiry
from catering_system.domain.inquiry_customer_snapshot import InquiryCustomerSnapshot
from catering_system.domain.order import Order, OrderVersion
from catering_system.domain.order_commercial_snapshot import (
    OrderCommercialPosition,
    OrderCommercialSnapshot,
)
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
from catering_system.services.customer_document_preview import (
    CustomerDocumentPreviewNotFoundError,
    CustomerDocumentPreviewService,
    build_customer_document_preview,
)
from catering_system.services.order_confirmation_document_service import (
    OrderConfirmationDocumentService,
)

_ORDER_ID = "22222222-2222-4222-8222-222222222222"
_VERSION_ID = "33333333-3333-4333-8333-333333333331"
_INQUIRY_ID = "99999999-9999-4999-8999-999999999999"
_SNAPSHOT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_OFFER_ID = "11111111-1111-4111-8111-111111111111"
_OFFER_VERSION_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
_POSITION_ID = "55555555-5555-4555-8555-555555555551"
_NOW = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
_PRINT_AT = datetime(2026, 7, 15, 13, 0, tzinfo=UTC)

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


def _inquiry(
    *,
    snapshot: InquiryCustomerSnapshot | None = None,
    fulfillment_mode: str = "PICKUP",
) -> Inquiry:
    return Inquiry(
        inquiry_id=_INQUIRY_ID,
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
        customer_snapshot=snapshot
        or InquiryCustomerSnapshot(
            company_name="ACME GmbH",
            contact_name="Anna",
            email="anna@example.invalid",
            phone="+49301234567",
        ),
        intake_message="Firma: SHOULD-NOT-USE\nE-Mail: intake@example.invalid\n",
        fulfillment_mode=fulfillment_mode,
    )


def _order() -> Order:
    return Order(
        order_id=_ORDER_ID,
        source_inquiry_id=_INQUIRY_ID,
        created_at=_NOW,
        updated_at=_NOW,
        effective_order_version_id=_VERSION_ID,
    )


def _version() -> OrderVersion:
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
        kitchen_print_confirmed_at=_PRINT_AT,
    )


def _commercial() -> OrderCommercialSnapshot:
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
        positions=(
            OrderCommercialPosition(
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
            ),
        ),
    )


def _codes(preview) -> tuple[str, ...]:
    return tuple(blocker.code for blocker in preview.blockers)


def test_valid_preview_is_eligible() -> None:
    preview = build_customer_document_preview(
        order=_order(),
        order_version=_version(),
        commercial_snapshot=_commercial(),
        recipient_inquiry=_inquiry(),
        now=_NOW,
    )
    assert preview.eligible is True
    assert preview.blockers == ()
    assert preview.recipient.name == "Anna"
    assert preview.recipient.company_name == "ACME GmbH"
    assert preview.commercial_reference is not None
    assert preview.commercial_reference.variant_label == "Variante A"
    assert preview.positions[0].name == "Fingerfood Paket"
    assert preview.gross_total_cents == 24824
    assert preview.event is not None
    assert preview.event.location_text == "Hamburg"


def test_missing_contact_preview_returns_blocker_not_exception() -> None:
    preview = build_customer_document_preview(
        order=_order(),
        order_version=_version(),
        commercial_snapshot=_commercial(),
        recipient_inquiry=_inquiry(
            snapshot=InquiryCustomerSnapshot(
                company_name="ACME GmbH",
                contact_name="Anna",
                email=None,
                phone=None,
            )
        ),
        now=_NOW,
    )
    assert preview.eligible is False
    assert "MISSING_CUSTOMER_CONTACT" in _codes(preview)
    assert preview.positions[0].name == "Fingerfood Paket"


def test_address_warning_keeps_preview_eligible() -> None:
    preview = build_customer_document_preview(
        order=_order(),
        order_version=_version(),
        commercial_snapshot=_commercial(),
        recipient_inquiry=_inquiry(fulfillment_mode="DELIVERY"),
        invoice_address=_INVOICE,
        delivery_address=_DELIVERY,
        now=_NOW,
    )
    assert preview.eligible is True
    assert WARNING_DELIVERY_ADDRESS_DIFFERS in preview.warnings
    assert preview.blockers == ()


def test_missing_commercial_preview_is_partial_and_ineligible() -> None:
    preview = build_customer_document_preview(
        order=_order(),
        order_version=_version(),
        commercial_snapshot=None,
        recipient_inquiry=_inquiry(),
        now=_NOW,
    )
    assert preview.eligible is False
    assert _codes(preview) == ("MISSING_COMMERCIAL_SNAPSHOT",)
    assert preview.commercial_reference is None
    assert preview.positions == ()
    assert preview.net_total_cents is None
    assert preview.event is not None
    assert preview.recipient.name == "Anna"


def test_preview_service_does_not_persist_confirmation_document() -> None:
    from tests.helpers.order_seed import seed_order

    orders = InMemoryOrderRepository()
    inquiries = InMemoryInquiryRepository()
    commercials = InMemoryOrderCommercialSnapshotRepository()
    documents = InMemoryOrderConfirmationDocumentRepository()
    inquiry = _inquiry()
    inquiries.save(inquiry)
    order, version = seed_order(
        orders,
        inquiry,
        order_id=_ORDER_ID,
        order_version_id=_VERSION_ID,
        created_at=_NOW,
    )
    orders.update_order_version(
        OrderVersion(
            order_version_id=version.order_version_id,
            order_id=order.order_id,
            version_number=1,
            created_at=_NOW,
            event_date=date(2026, 8, 20),
            time_window_text="18:00–22:00",
            location_text="Hamburg",
            guest_count_estimate=80,
            planning_mode="caterer_suggestion",
            kitchen_print_confirmed_at=_PRINT_AT,
        )
    )
    orders.update_order(
        Order(
            order_id=order.order_id,
            source_inquiry_id=inquiry.inquiry_id,
            created_at=_NOW,
            updated_at=_NOW,
            effective_order_version_id=version.order_version_id,
        )
    )
    commercials.create(_commercial())

    preview_service = CustomerDocumentPreviewService(
        orders, inquiries, commercials, now=lambda: _NOW
    )
    preview = preview_service.preview_order_confirmation(_ORDER_ID)
    assert preview.eligible is True
    assert documents.get_latest_for_order(_ORDER_ID) is None

    confirmation = OrderConfirmationDocumentService(
        orders, inquiries, documents, commercials, now=lambda: _NOW
    )
    confirmation.prepare_snapshot(_ORDER_ID, _VERSION_ID, "office-panel")
    assert documents.get_latest_for_order(_ORDER_ID) is not None


def test_preview_service_unknown_order_raises() -> None:
    service = CustomerDocumentPreviewService(
        InMemoryOrderRepository(),
        InMemoryInquiryRepository(),
        InMemoryOrderCommercialSnapshotRepository(),
    )
    with pytest.raises(CustomerDocumentPreviewNotFoundError):
        service.preview_order_confirmation(_ORDER_ID)


def test_preview_modules_boundary() -> None:
    root = Path(__file__).resolve().parents[2] / "src" / "catering_system"
    for relative in (
        "domain/customer_document_preview.py",
        "services/customer_document_preview.py",
    ):
        text = (root / relative).read_text(encoding="utf-8")
        assert "OfferRepository" not in text, relative
        assert "conversion_link" not in text, relative
        assert "parse_intake_contact" not in text, relative
        assert "labelled_intake_context" not in text, relative
        assert "OrderConfirmationDocumentSnapshot" not in text, relative
