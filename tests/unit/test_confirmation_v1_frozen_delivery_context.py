"""M2a regression: V1 confirmation delivery follows frozen OrderVersion context."""

from __future__ import annotations

from dataclasses import replace

from catering_system.domain.customer_document_projection import CustomerAddress
from catering_system.domain.inquiry_customer_snapshot import (
    set_inquiry_customer_addresses,
)
from catering_system.repositories.in_memory_order_confirmation_document_repository import (
    InMemoryOrderConfirmationDocumentRepository,
)
from catering_system.services.customer_document_preview import (
    CustomerDocumentPreviewService,
)
from catering_system.services.operational_core_service import OperationalCoreService
from catering_system.services.order_confirmation_document_service import (
    OrderConfirmationDocumentService,
)
from tests.unit.test_offer_service import _accepted_offer_state

_INVOICE = CustomerAddress(
    street="Bürostraße 1",
    postal_code="20095",
    city="Hamburg",
    country="DE",
)
_INITIAL_DELIVERY = CustomerAddress(
    street="Alter Lieferweg 9",
    postal_code="20457",
    city="Hamburg",
    country="DE",
)
_LATER_DELIVERY = CustomerAddress(
    street="Brombeerenstraße 4",
    postal_code="22041",
    city="Hamburg",
    country="DE",
)


def _set_live_delivery(
    inquiries: object, inquiry_id: str, address: CustomerAddress
) -> None:
    inquiry = inquiries.get_by_id(inquiry_id)  # type: ignore[attr-defined]
    assert inquiry is not None
    updated = set_inquiry_customer_addresses(
        inquiry,
        invoice_address=_INVOICE,
        delivery_address=address,
        delivery_address_mode="SEPARATE",
    )
    inquiries.update(  # type: ignore[attr-defined]
        replace(updated, fulfillment_mode="DELIVERY")
    )


def _v1_world(*, initial_delivery: CustomerAddress | None):
    (
        offer,
        version_id,
        variant_id,
        acceptance_id,
        _offers,
        orders,
        inquiries,
        offer_service,
    ) = _accepted_offer_state()

    if initial_delivery is not None:
        _set_live_delivery(inquiries, offer.source_inquiry_id, initial_delivery)

    _converted, order, v1 = offer_service.convert_accepted_offer(
        offer.offer_id,
        version_id,
        variant_id,
        acceptance_id,
    )
    core = OperationalCoreService(orders)
    core.confirm_kitchen_print(order.order_id, v1.order_version_id)
    core.make_order_version_effective(order.order_id, v1.order_version_id)

    documents = InMemoryOrderConfirmationDocumentRepository()
    service = OrderConfirmationDocumentService(
        orders,
        inquiries,
        documents,
        offer_service._commercial_snapshots,
    )
    preview_service = CustomerDocumentPreviewService(
        orders,
        inquiries,
        offer_service._commercial_snapshots,
    )
    return orders, inquiries, service, preview_service, order, v1


def test_v1_known_delivery_stays_frozen_after_inquiry_change() -> None:
    orders, inquiries, service, preview_service, order, v1 = _v1_world(
        initial_delivery=_INITIAL_DELIVERY
    )
    context = orders.get_operational_context(v1.order_version_id)
    assert context is not None
    assert context.delivery_address == _INITIAL_DELIVERY

    _set_live_delivery(inquiries, order.source_inquiry_id, _LATER_DELIVERY)

    preview = preview_service.preview_order_confirmation(order.order_id)
    assert preview.recipient.invoice_address == _INVOICE
    assert preview.recipient.delivery_address == _INITIAL_DELIVERY

    snapshot = service.prepare_snapshot(
        order.order_id,
        v1.order_version_id,
        "office-panel",
    )
    assert snapshot.invoice_address == _INVOICE
    assert snapshot.delivery_address == _INITIAL_DELIVERY
    assert snapshot.delivery_address_differs is True


def test_v1_missing_delivery_can_be_completed_before_first_confirmation() -> None:
    orders, inquiries, service, preview_service, order, v1 = _v1_world(
        initial_delivery=None
    )
    context = orders.get_operational_context(v1.order_version_id)
    assert context is not None
    assert context.delivery_address is None

    _set_live_delivery(inquiries, order.source_inquiry_id, _LATER_DELIVERY)

    preview = preview_service.preview_order_confirmation(order.order_id)
    assert preview.recipient.invoice_address == _INVOICE
    assert preview.recipient.delivery_address == _LATER_DELIVERY

    snapshot = service.prepare_snapshot(
        order.order_id,
        v1.order_version_id,
        "office-panel",
    )
    assert snapshot.invoice_address == _INVOICE
    assert snapshot.delivery_address == _LATER_DELIVERY
    assert snapshot.delivery_address_differs is True
