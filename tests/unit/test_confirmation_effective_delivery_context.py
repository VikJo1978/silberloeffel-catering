"""Regression coverage for confirmation delivery address from effective OrderVersion."""

from __future__ import annotations

from dataclasses import replace

from catering_system.domain.customer_document_projection import CustomerAddress
from catering_system.domain.inquiry_customer_snapshot import (
    set_inquiry_customer_addresses,
)
from catering_system.services.customer_document_preview import (
    CustomerDocumentPreviewService,
)
from catering_system.services.order_service import OrderService
from tests.unit.test_order_confirmation_document import _effective_order, _services

_INVOICE = CustomerAddress(
    street="Bürostraße 1",
    postal_code="20095",
    city="Hamburg",
    country="DE",
)
_DELIVERY = CustomerAddress(
    street="brombeeren str 4",
    postal_code="22041",
    city="Hamburg",
    country="DE",
)
_OLD_DELIVERY = CustomerAddress(
    street="Alter Lieferweg 9",
    postal_code="20457",
    city="Hamburg",
    country="DE",
)


def _set_delivery_inquiry(
    inquiries: object,
    order: object,
    *,
    delivery_address: CustomerAddress | None,
) -> None:
    inquiry = inquiries.get_by_id(  # type: ignore[attr-defined]
        order.source_inquiry_id  # type: ignore[attr-defined]
    )
    assert inquiry is not None
    mode = "SEPARATE" if delivery_address is not None else "UNKNOWN"
    updated = set_inquiry_customer_addresses(
        inquiry,
        invoice_address=_INVOICE,
        delivery_address=delivery_address,
        delivery_address_mode=mode,
    )
    inquiries.update(  # type: ignore[attr-defined]
        replace(updated, fulfillment_mode="DELIVERY")
    )


def test_effective_delivery_change_drives_confirmation_context() -> None:
    services = _services()
    orders, _offers, inquiries, _documents, service, core, offer_service = services
    order, v1 = _effective_order(services)
    _set_delivery_inquiry(inquiries, order, delivery_address=None)

    v2 = OrderService(orders).propose_delivery_address_change(
        order.order_id,
        parent_order_version_id=v1.order_version_id,
        delivery_address=_DELIVERY,
        actor_reference="office-panel",
        change_reason="Lieferadresse geändert",
    )

    candidate_order = orders.get_order(order.order_id)
    assert candidate_order is not None
    candidate_decision = service._evaluate_create(candidate_order)
    assert candidate_decision.allowed is False
    assert "INVALID_ORDER_STATE" in {
        blocker.code for blocker in candidate_decision.blockers
    }

    core.confirm_kitchen_print(order.order_id, v2.order_version_id)
    core.make_order_version_effective(order.order_id, v2.order_version_id)

    refreshed = orders.get_order(order.order_id)
    assert refreshed is not None
    inquiry = inquiries.get_by_id(order.source_inquiry_id)
    assert inquiry is not None
    assert inquiry.customer_snapshot is not None
    assert inquiry.customer_snapshot.delivery_address is None
    assert inquiry.customer_snapshot.delivery_address_mode == "UNKNOWN"

    eligibility = service.eligibility(order.order_id)
    assert eligibility.can_prepare is True

    preview_service = CustomerDocumentPreviewService(
        orders,
        inquiries,
        offer_service._commercial_snapshots,
    )
    preview = preview_service.preview_order_confirmation(order.order_id)
    assert preview.eligible is True
    assert preview.recipient.invoice_address == _INVOICE
    assert preview.recipient.delivery_address == _DELIVERY

    snapshot = service.prepare_snapshot(
        order.order_id,
        v2.order_version_id,
        "office-panel",
    )
    assert snapshot.order_version_id == v2.order_version_id
    assert snapshot.invoice_address == _INVOICE
    assert snapshot.delivery_address == _DELIVERY
    assert snapshot.delivery_address_differs is True


def test_effective_delivery_removal_does_not_fall_back_to_stale_inquiry() -> None:
    services = _services()
    orders, _offers, inquiries, _documents, service, core, offer_service = services
    order, v1 = _effective_order(services)
    _set_delivery_inquiry(inquiries, order, delivery_address=_OLD_DELIVERY)

    v2 = OrderService(orders).propose_delivery_address_change(
        order.order_id,
        parent_order_version_id=v1.order_version_id,
        delivery_address=None,
        actor_reference="office-panel",
        change_reason="Lieferadresse entfernt",
    )
    core.confirm_kitchen_print(order.order_id, v2.order_version_id)
    core.make_order_version_effective(order.order_id, v2.order_version_id)

    current_order = orders.get_order(order.order_id)
    assert current_order is not None
    decision = service._evaluate_create(current_order)
    assert decision.allowed is False
    assert "DELIVERY_ADDRESS_REQUIRED_FOR_DELIVERY" in {
        blocker.code for blocker in decision.blockers
    }

    preview_service = CustomerDocumentPreviewService(
        orders,
        inquiries,
        offer_service._commercial_snapshots,
    )
    preview = preview_service.preview_order_confirmation(order.order_id)
    assert preview.eligible is False
    assert preview.recipient.invoice_address == _INVOICE
    assert preview.recipient.delivery_address is None
    assert "DELIVERY_ADDRESS_REQUIRED_FOR_DELIVERY" in {
        blocker.code for blocker in preview.blockers
    }
