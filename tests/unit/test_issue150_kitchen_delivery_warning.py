"""Issue #150: kitchen output highlights a delivery address that differs from invoice."""

from __future__ import annotations

import io
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any, cast

from pypdf import PdfReader

from catering_system.domain.customer_document_projection import CustomerAddress
from catering_system.domain.order_operational_context import (
    OrderVersionOperationalContextSnapshot,
)
from catering_system.services.kitchen_print_pdf_renderer import (
    render_kitchen_print_pdf,
)
from catering_system.services.order_print_projection_service import (
    OrderPrintProjection,
    PrintCommercialBlock,
    PrintCustomerBlock,
    PrintEventBlock,
    PrintFlagsBlock,
    _customer_block,
)

_NOW = datetime(2026, 8, 22, 9, 0, tzinfo=UTC)
_INVOICE = CustomerAddress(
    street="Rechnungsweg 1",
    postal_code="20095",
    city="Hamburg",
    country="DE",
)
_DELIVERY = CustomerAddress(
    street="Eventweg 9",
    postal_code="22767",
    city="Hamburg",
    country="DE",
)


def _operational(address: CustomerAddress) -> OrderVersionOperationalContextSnapshot:
    return OrderVersionOperationalContextSnapshot(
        order_version_id="22222222-2222-4222-8222-222222222222",
        order_id="11111111-1111-4111-8111-111111111111",
        recipient_company="Beispiel GmbH",
        recipient_name="Ada Beispiel",
        recipient_phone="+49 40 123456",
        delivery_address=address,
        created_at=_NOW,
        source="initial_inquiry_snapshot",
    )


def _confirmation(invoice_address: CustomerAddress) -> Any:
    return SimpleNamespace(
        invoice_address=invoice_address,
        fulfillment_mode="DELIVERY",
    )


def _projection(customer: PrintCustomerBlock) -> OrderPrintProjection:
    return OrderPrintProjection(
        event=PrintEventBlock(
            order_id="11111111-1111-4111-8111-111111111111",
            order_version_id="22222222-2222-4222-8222-222222222222",
            version_number=1,
            event_date=date(2026, 9, 1),
            time_window_text="18:00",
            location_text="Hamburg",
            guest_count_estimate=20,
            planning_mode="caterer_suggestion",
            kitchen_print_confirmed_at=_NOW,
            order_cancelled_at=None,
            is_candidate=False,
            is_effective=True,
        ),
        commercial=PrintCommercialBlock(source="offer_conversion"),
        flags=PrintFlagsBlock(
            intent="kitchen_job",
            is_preview=False,
            is_final_allowed=False,
            is_stale=False,
            watermark=None,
        ),
        customer=customer,
    )


def _pdf_text(projection: OrderPrintProjection) -> str:
    body = render_kitchen_print_pdf(projection, created_at=_NOW)
    return "\n".join(
        page.extract_text() or "" for page in PdfReader(io.BytesIO(body)).pages
    )


def test_print_customer_derives_difference_from_structured_addresses() -> None:
    customer = _customer_block(
        _operational(_DELIVERY),
        confirmation_snapshot=cast(Any, _confirmation(_INVOICE)),
    )

    assert customer.delivery_address_differs is True
    assert customer.delivery_address_lines == ("Eventweg 9", "22767 Hamburg", "DE")
    assert customer.fulfillment_mode == "DELIVERY"


def test_print_customer_normalizes_equal_structured_addresses() -> None:
    same_invoice = CustomerAddress(
        street="  EVENTWEG   9 ",
        postal_code="22767",
        city="hamburg",
        country="de",
    )
    customer = _customer_block(
        _operational(_DELIVERY),
        confirmation_snapshot=cast(Any, _confirmation(same_invoice)),
    )

    assert customer.delivery_address_differs is False


def test_kitchen_pdf_prominently_warns_and_prints_actual_delivery_address() -> None:
    customer = PrintCustomerBlock(
        company_name="Beispiel GmbH",
        contact_name="Ada Beispiel",
        phone="+49 40 123456",
        delivery_address_lines=("Eventweg 9", "22767 Hamburg", "DE"),
        fulfillment_mode="DELIVERY",
        delivery_address_differs=True,
    )

    text = _pdf_text(_projection(customer))

    assert "Lieferadresse weicht von Rechnungsadresse ab" in text
    assert "Eventweg 9" in text
    assert "22767 Hamburg" in text


def test_kitchen_pdf_omits_warning_when_addresses_do_not_differ() -> None:
    customer = PrintCustomerBlock(
        delivery_address_lines=("Rechnungsweg 1", "20095 Hamburg", "DE"),
        fulfillment_mode="DELIVERY",
        delivery_address_differs=False,
    )

    text = _pdf_text(_projection(customer))

    assert "Lieferadresse weicht von Rechnungsadresse ab" not in text
