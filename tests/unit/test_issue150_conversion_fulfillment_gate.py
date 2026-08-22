"""Issue #150: defensive Accepted Offer -> Order fulfillment gate."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime

from catering_system.domain.customer_document_projection import CustomerAddress
from catering_system.domain.inquiry import Inquiry, inquiry_allows_order_conversion
from catering_system.domain.inquiry_customer_snapshot import InquiryCustomerSnapshot

_NOW = datetime(2026, 8, 22, 6, 0, tzinfo=UTC)
_COMPLETE = CustomerAddress(
    street="Bürostraße 1",
    postal_code="20095",
    city="Hamburg",
    country="DE",
)


def _inquiry(*, fulfillment_mode: str, snapshot: InquiryCustomerSnapshot | None) -> Inquiry:
    return Inquiry(
        inquiry_id="11111111-1111-4111-8111-111111111111",
        event_date=date(2026, 9, 1),
        created_at=_NOW,
        updated_at=_NOW,
        inquiry_source="manual",
        crm_stage="Angebot gesendet / Rückmeldung offen",
        customer_linkage={},
        time_window_text="18:00",
        location_text="Hamburg",
        guest_count_estimate=20,
        planning_mode="caterer_suggestion",
        call_verification_required=False,
        call_verification_status="not_required",
        customer_snapshot=snapshot,
        fulfillment_mode=fulfillment_mode,  # type: ignore[arg-type]
    )


def test_pickup_conversion_never_requires_delivery_address() -> None:
    assert inquiry_allows_order_conversion(
        _inquiry(fulfillment_mode="PICKUP", snapshot=None)
    )


def test_delivery_same_as_invoice_requires_complete_invoice_address() -> None:
    missing = InquiryCustomerSnapshot(delivery_address_mode="SAME_AS_INVOICE")
    assert not inquiry_allows_order_conversion(
        _inquiry(fulfillment_mode="DELIVERY", snapshot=missing)
    )

    resolved = replace(missing, invoice_address=_COMPLETE)
    assert inquiry_allows_order_conversion(
        _inquiry(fulfillment_mode="DELIVERY", snapshot=resolved)
    )


def test_delivery_separate_requires_complete_delivery_address() -> None:
    partial = InquiryCustomerSnapshot(
        invoice_address=_COMPLETE,
        delivery_address_mode="SEPARATE",
        delivery_address=CustomerAddress(street="Eventweg 2", city="Hamburg"),
    )
    assert not inquiry_allows_order_conversion(
        _inquiry(fulfillment_mode="DELIVERY", snapshot=partial)
    )

    resolved = replace(partial, delivery_address=_COMPLETE)
    assert inquiry_allows_order_conversion(
        _inquiry(fulfillment_mode="DELIVERY", snapshot=resolved)
    )


def test_unknown_stays_legacy_compatible_at_defensive_conversion_gate() -> None:
    assert inquiry_allows_order_conversion(
        _inquiry(fulfillment_mode="UNKNOWN", snapshot=None)
    )
