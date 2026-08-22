"""Issue #150: accepted fulfillment/address facts carry into Order operational context."""

from __future__ import annotations

from dataclasses import replace

from catering_system.domain.customer_document_projection import CustomerAddress
from tests.unit.test_offer_service import _accepted_offer_state

_INVOICE = CustomerAddress(
    street="Bürostraße 1",
    postal_code="20095",
    city="Hamburg",
    country="DE",
)
_DELIVERY = CustomerAddress(
    street="Eventweg 2",
    postal_code="20354",
    city="Hamburg",
    country="DE",
)


def _set_fulfillment_context(
    inquiries,  # noqa: ANN001
    inquiry_id: str,
    *,
    fulfillment_mode: str,
    delivery_address_mode: str,
    invoice_address: CustomerAddress | None = _INVOICE,
    delivery_address: CustomerAddress | None = None,
) -> None:
    inquiry = inquiries.get_by_id(inquiry_id)
    assert inquiry is not None
    assert inquiry.customer_snapshot is not None
    inquiries.update(
        replace(
            inquiry,
            fulfillment_mode=fulfillment_mode,
            customer_snapshot=replace(
                inquiry.customer_snapshot,
                invoice_address=invoice_address,
                delivery_address_mode=delivery_address_mode,
                delivery_address=delivery_address,
            ),
        )
    )


def _convert_with_context(
    *,
    fulfillment_mode: str,
    delivery_address_mode: str,
    delivery_address: CustomerAddress | None = None,
):
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
    _set_fulfillment_context(
        inquiries,
        offer.source_inquiry_id,
        fulfillment_mode=fulfillment_mode,
        delivery_address_mode=delivery_address_mode,
        delivery_address=delivery_address,
    )

    _updated, order, order_version = service.convert_accepted_offer(
        offer.offer_id,
        version_id,
        variant_id,
        acceptance_id,
    )
    context = orders.get_operational_context(order_version.order_version_id)
    assert context is not None
    assert context.order_id == order.order_id
    return context


def test_delivery_same_as_invoice_reuses_invoice_address_in_order() -> None:
    context = _convert_with_context(
        fulfillment_mode="DELIVERY",
        delivery_address_mode="SAME_AS_INVOICE",
    )

    assert context.delivery_address == _INVOICE


def test_delivery_separate_carries_actual_delivery_address_into_order() -> None:
    context = _convert_with_context(
        fulfillment_mode="DELIVERY",
        delivery_address_mode="SEPARATE",
        delivery_address=_DELIVERY,
    )

    assert context.delivery_address == _DELIVERY


def test_pickup_carries_no_delivery_address_even_if_one_is_stored() -> None:
    context = _convert_with_context(
        fulfillment_mode="PICKUP",
        delivery_address_mode="SEPARATE",
        delivery_address=_DELIVERY,
    )

    assert context.delivery_address is None
