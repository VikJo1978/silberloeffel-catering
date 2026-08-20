"""Regression coverage for confirmation snapshot replay after version changes."""

from datetime import date

import pytest

from catering_system.services.order_confirmation_document_service import (
    OrderConfirmationDocumentStaleVersionError,
)
from catering_system.services.order_service import OrderService
from tests.unit.test_order_confirmation_document import _effective_order, _services


def test_prepare_rejects_old_snapshot_replay_after_effective_version_changes() -> None:
    services = _services()
    orders, _offers, _inquiries, documents, service, core, _offer_service = services
    order, v1 = _effective_order(services)
    first = service.prepare_snapshot(
        order.order_id,
        v1.order_version_id,
        "office-panel",
    )

    v2 = OrderService(orders).propose_order_version_change(
        order.order_id,
        event_date=date(2026, 9, 2),
        time_window_text=v1.time_window_text,
        location_text="Kiel",
        guest_count_estimate=v1.guest_count_estimate,
        planning_mode=v1.planning_mode,
        actor_reference="office-panel",
        change_reason="Ort geändert",
    )
    core.confirm_kitchen_print(order.order_id, v2.order_version_id)
    core.make_order_version_effective(order.order_id, v2.order_version_id)

    with pytest.raises(OrderConfirmationDocumentStaleVersionError):
        service.prepare_snapshot(
            order.order_id,
            v1.order_version_id,
            "office-panel",
        )

    stored = documents.get_by_id(first.document_snapshot_id)
    assert stored is not None
    assert stored.document_snapshot_id == first.document_snapshot_id
    assert (
        service.get_snapshot(order.order_id, first.document_snapshot_id)
        .document_snapshot_id
        == first.document_snapshot_id
    )
