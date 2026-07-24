"""CUSTOMER_DOCUMENT_PROJECTION_V1-C-1 — pure create eligibility."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from catering_system.domain.customer_document_eligibility import (
    CustomerDocumentEligibility,
    DocumentBlocker,
)
from catering_system.domain.customer_document_projection import (
    WARNING_DELIVERY_ADDRESS_DIFFERS,
    CustomerAddress,
    CustomerDocumentRecipient,
)
from catering_system.domain.order import Order, OrderVersion
from catering_system.domain.order_commercial_snapshot import (
    OrderCommercialPosition,
    OrderCommercialSnapshot,
)
from catering_system.services.customer_document_eligibility import (
    evaluate_customer_document_eligibility,
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


def _order(
    *,
    cancelled: bool = False,
    effective: str | None = _VERSION_ID,
    candidate: str | None = None,
) -> Order:
    return Order(
        order_id=_ORDER_ID,
        source_inquiry_id=_INQUIRY_ID,
        created_at=_NOW,
        updated_at=_NOW,
        effective_order_version_id=effective,
        candidate_order_version_id=candidate,
        cancelled_at=_NOW if cancelled else None,
    )


def _version(*, kitchen_print: bool = True) -> OrderVersion:
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
        kitchen_print_confirmed_at=_PRINT_AT if kitchen_print else None,
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


def _recipient(
    *,
    name: str = "Anna",
    email: str | None = "anna@example.invalid",
    company_name: str | None = "ACME GmbH",
    phone: str | None = "+49301234567",
    invoice_address: CustomerAddress | None = None,
    delivery_address: CustomerAddress | None = None,
) -> CustomerDocumentRecipient:
    differs = (
        invoice_address is not None
        and delivery_address is not None
        and invoice_address != delivery_address
    )
    return CustomerDocumentRecipient(
        name=name,
        email=email,
        company_name=company_name,
        phone=phone,
        invoice_address=invoice_address,
        delivery_address=delivery_address,
        delivery_address_differs=differs,
        warnings=(WARNING_DELIVERY_ADDRESS_DIFFERS,) if differs else (),
    )


def _codes(result: CustomerDocumentEligibility) -> tuple[str, ...]:
    return tuple(blocker.code for blocker in result.blockers)


def test_valid_order_is_allowed() -> None:
    result = evaluate_customer_document_eligibility(
        order=_order(),
        order_version=_version(),
        commercial_snapshot=_commercial(),
        recipient=_recipient(),
        fulfillment_mode="PICKUP",
    )
    assert result.allowed is True
    assert result.blockers == ()


def test_missing_commercial_snapshot_blocks() -> None:
    result = evaluate_customer_document_eligibility(
        order=_order(),
        order_version=_version(),
        commercial_snapshot=None,
        recipient=_recipient(),
        fulfillment_mode="PICKUP",
    )
    assert result.allowed is False
    assert _codes(result) == ("MISSING_COMMERCIAL_SNAPSHOT",)


def test_cancelled_order_blocks_with_invalid_order_state() -> None:
    result = evaluate_customer_document_eligibility(
        order=_order(cancelled=True),
        order_version=_version(),
        commercial_snapshot=_commercial(),
        recipient=_recipient(),
        fulfillment_mode="PICKUP",
    )
    assert result.allowed is False
    assert _codes(result) == ("INVALID_ORDER_STATE",)


def test_candidate_and_missing_kitchen_print_are_invalid_order_state() -> None:
    candidate = evaluate_customer_document_eligibility(
        order=_order(candidate="cccccccc-cccc-4ccc-8ccc-cccccccccccc"),
        order_version=_version(),
        commercial_snapshot=_commercial(),
        recipient=_recipient(),
        fulfillment_mode="PICKUP",
    )
    assert candidate.allowed is False
    assert _codes(candidate) == ("INVALID_ORDER_STATE",)

    no_print = evaluate_customer_document_eligibility(
        order=_order(),
        order_version=_version(kitchen_print=False),
        commercial_snapshot=_commercial(),
        recipient=_recipient(),
        fulfillment_mode="PICKUP",
    )
    assert no_print.allowed is False
    assert _codes(no_print) == ("INVALID_ORDER_STATE",)


def test_missing_customer_name_and_contact_block() -> None:
    result = evaluate_customer_document_eligibility(
        order=_order(),
        order_version=_version(),
        commercial_snapshot=_commercial(),
        recipient=_recipient(
            name="Kunde",
            email=None,
            company_name=None,
            phone=None,
        ),
        fulfillment_mode="PICKUP",
    )
    assert result.allowed is False
    assert _codes(result) == (
        "MISSING_CUSTOMER_NAME",
        "MISSING_CUSTOMER_CONTACT",
    )


def test_company_name_alone_satisfies_name_requirement() -> None:
    result = evaluate_customer_document_eligibility(
        order=_order(),
        order_version=_version(),
        commercial_snapshot=_commercial(),
        recipient=_recipient(
            name="Kunde",
            company_name="ACME GmbH",
            email="anna@example.invalid",
            phone=None,
        ),
        fulfillment_mode="PICKUP",
    )
    assert result.allowed is True
    assert result.blockers == ()


def test_phone_alone_satisfies_contact_requirement() -> None:
    result = evaluate_customer_document_eligibility(
        order=_order(),
        order_version=_version(),
        commercial_snapshot=_commercial(),
        recipient=_recipient(
            name="Anna",
            email=None,
            phone="+49301234567",
        ),
        fulfillment_mode="PICKUP",
    )
    assert result.allowed is True
    assert result.blockers == ()


def test_address_warning_does_not_block_eligibility() -> None:
    recipient = _recipient(invoice_address=_INVOICE, delivery_address=_DELIVERY)
    assert WARNING_DELIVERY_ADDRESS_DIFFERS in recipient.warnings
    result = evaluate_customer_document_eligibility(
        order=_order(),
        order_version=_version(),
        commercial_snapshot=_commercial(),
        recipient=recipient,
        fulfillment_mode="DELIVERY",
    )
    assert result.allowed is True
    assert result.blockers == ()


def test_eligibility_invariant_rejects_inconsistent_state() -> None:
    with pytest.raises(ValueError, match="allowed must equal"):
        CustomerDocumentEligibility(
            allowed=True,
            blockers=(DocumentBlocker(code="INVALID_ORDER_STATE"),),
        )
    with pytest.raises(ValueError, match="allowed must equal"):
        CustomerDocumentEligibility(allowed=False, blockers=())


def test_eligibility_modules_must_not_depend_on_offer_or_channels() -> None:
    root = Path(__file__).resolve().parents[2] / "src" / "catering_system"
    for relative in (
        "domain/customer_document_eligibility.py",
        "services/customer_document_eligibility.py",
    ):
        text = (root / relative).read_text(encoding="utf-8")
        assert "OfferRepository" not in text, relative
        assert "offer_repository" not in text, relative
        assert "conversion_link" not in text, relative
        assert "parse_intake_contact" not in text, relative
        assert "labelled_intake_context" not in text, relative
        assert "smtp" not in text.lower(), relative
        assert "weasyprint" not in text.lower(), relative
        assert "order_confirmation_document_preview" not in text, relative
        assert "OrderConfirmationOutbound" not in text, relative
