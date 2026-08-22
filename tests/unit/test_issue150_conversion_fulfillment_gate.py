"""Issue #150: defensive Accepted Offer -> Order fulfillment gate."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from catering_system.domain.customer_document_projection import CustomerAddress
from catering_system.domain.inquiry import Inquiry, inquiry_allows_order_conversion
from catering_system.domain.inquiry_customer_snapshot import InquiryCustomerSnapshot
from tests.unit.test_offer_service import _accepted_offer_state

_NOW = datetime(2026, 8, 22, 6, 0, tzinfo=UTC)
_COMPLETE = CustomerAddress(
    street="Bürostraße 1",
    postal_code="20095",
    city="Hamburg",
    country="DE",
)


def _inquiry(
    *, fulfillment_mode: str, snapshot: InquiryCustomerSnapshot | None
) -> Inquiry:
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


def _set_unresolved_delivery(inquiries, inquiry_id: str) -> None:  # noqa: ANN001
    inquiry = inquiries.get_by_id(inquiry_id)
    assert inquiry is not None
    assert inquiry.customer_snapshot is not None
    unresolved = replace(
        inquiry.customer_snapshot,
        invoice_address=None,
        delivery_address=None,
        delivery_address_mode="UNKNOWN",
    )
    inquiries.update(
        replace(
            inquiry,
            fulfillment_mode="DELIVERY",
            customer_snapshot=unresolved,
        )
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


def test_new_accepted_offer_conversion_rejects_unresolved_delivery() -> None:
    (
        offer,
        version_id,
        variant_id,
        acceptance_id,
        _offers,
        orders,
        inquiries,
        service,
    ) = _accepted_offer_state()
    _set_unresolved_delivery(inquiries, offer.source_inquiry_id)

    with pytest.raises(ValueError, match="delivery context unresolved"):
        service.convert_accepted_offer(
            offer.offer_id,
            version_id,
            variant_id,
            acceptance_id,
        )

    assert orders.list_orders() == []


def test_existing_conversion_replay_ignores_later_unresolved_delivery() -> None:
    (
        offer,
        version_id,
        variant_id,
        acceptance_id,
        _offers,
        orders,
        inquiries,
        service,
    ) = _accepted_offer_state()
    first = service.convert_accepted_offer(
        offer.offer_id,
        version_id,
        variant_id,
        acceptance_id,
    )
    _set_unresolved_delivery(inquiries, offer.source_inquiry_id)

    replay = service.convert_accepted_offer(
        offer.offer_id,
        version_id,
        variant_id,
        acceptance_id,
    )

    assert replay[1].order_id == first[1].order_id
    assert len(orders.list_orders()) == 1
