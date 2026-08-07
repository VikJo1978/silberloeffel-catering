"""Slice 6 contract tests — Delivery Execution boundary (PR B).

Proves KitchenCompletionEvidence handoff drives delivery queue membership,
PICKUP exclusion, and frozen delivery snapshot boundary. No domain/API changes.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from catering_system.repositories.in_memory_kitchen_completion_evidence_repository import (
    InMemoryKitchenCompletionEvidenceRepository,
)
from catering_system.repositories.in_memory_order_commercial_snapshot_repository import (
    InMemoryOrderCommercialSnapshotRepository,
)
from catering_system.repositories.in_memory_order_repository import (
    InMemoryOrderRepository,
)
from catering_system.services.kitchen_execution_service import KitchenExecutionService
from catering_system.services.operational_core_service import OperationalCoreService
from tests.helpers.delivery_queue_contract import build_delivery_queue_projection
from tests.helpers.delivery_snapshot_contract import (
    InMemoryOrderDeliverySnapshotRepository,
    seed_delivery_snapshot,
)
from tests.helpers.kitchen_queue_contract import build_kitchen_queue_projection
from tests.unit.test_offer_service import _accepted_offer_state

_NOW = datetime(2026, 8, 7, 14, 0, tzinfo=UTC)


def _ready_released_order() -> tuple[
    InMemoryOrderRepository,
    InMemoryOrderCommercialSnapshotRepository,
    InMemoryKitchenCompletionEvidenceRepository,
    InMemoryOrderDeliverySnapshotRepository,
    str,
    str,
]:
    offer, version_id, variant_id, acceptance_id, _offers, orders, _inq, service = (
        _accepted_offer_state()
    )
    _converted, order, order_version = service.convert_accepted_offer(
        offer.offer_id,
        version_id,
        variant_id,
        acceptance_id,
    )
    commercial = service._commercial_snapshots
    core = OperationalCoreService(orders)
    core.confirm_kitchen_print(order.order_id, order_version.order_version_id)
    core.make_order_version_effective(order.order_id, order_version.order_version_id)
    assert core.evaluate_ready_to_send(order.order_id).ready is True

    delivery_snapshots = InMemoryOrderDeliverySnapshotRepository()
    seed_delivery_snapshot(
        delivery_snapshots,
        order_id=order.order_id,
        order_version_id=order_version.order_version_id,
        time_window_text=order_version.time_window_text,
        location_text=order_version.location_text,
    )
    kitchen_evidence = InMemoryKitchenCompletionEvidenceRepository()
    return (
        orders,
        commercial,
        kitchen_evidence,
        delivery_snapshots,
        order.order_id,
        order_version.order_version_id,
    )


def _delivery_queue_order_ids(
    orders: InMemoryOrderRepository,
    kitchen_evidence: InMemoryKitchenCompletionEvidenceRepository,
    delivery_snapshots: InMemoryOrderDeliverySnapshotRepository,
) -> set[str]:
    return {
        entry.order_id
        for entry in build_delivery_queue_projection(
            orders,
            kitchen_evidence,
            delivery_snapshots,
        )
    }


def test_delivery_queue_excludes_ready_order_without_kitchen_completion() -> None:
    orders, commercial, kitchen_evidence, delivery_snapshots, order_id, version_id = (
        _ready_released_order()
    )
    core = OperationalCoreService(orders)
    assert core.evaluate_ready_to_send(order_id).ready is True
    assert len(build_kitchen_queue_projection(orders, commercial)) == 1

    assert order_id not in _delivery_queue_order_ids(
        orders,
        kitchen_evidence,
        delivery_snapshots,
    )

    KitchenExecutionService(
        orders,
        kitchen_evidence,
        clock=lambda: _NOW,
    ).record_kitchen_completion(
        order_id,
        version_id,
        completed_at=_NOW,
        recorded_by="kitchen-panel",
        evidence_reference="ticket-42",
    )
    assert order_id in _delivery_queue_order_ids(
        orders,
        kitchen_evidence,
        delivery_snapshots,
    )


def test_delivery_queue_includes_order_after_kitchen_completion_from_frozen_snapshot() -> (
    None
):
    orders, _commercial, kitchen_evidence, delivery_snapshots, order_id, version_id = (
        _ready_released_order()
    )
    KitchenExecutionService(
        orders,
        kitchen_evidence,
        clock=lambda: _NOW,
    ).record_kitchen_completion(
        order_id,
        version_id,
        completed_at=_NOW,
        recorded_by="kitchen-panel",
        evidence_reference="ticket-42",
    )

    queue = build_delivery_queue_projection(
        orders,
        kitchen_evidence,
        delivery_snapshots,
    )
    assert len(queue) == 1
    entry = queue[0]
    assert entry.order_id == order_id
    assert entry.order_version_id == version_id
    assert entry.delivery_snapshot.created_from == "accepted_order_conversion"
    assert entry.delivery_snapshot.fulfillment_mode == "DELIVERY"
    assert entry.delivery_snapshot.time_window_text == "18:00–22:00"
    assert entry.delivery_snapshot.location_text == "Hamburg"


def test_delivery_queue_excludes_pickup_fulfillment_mode() -> None:
    orders, _commercial, kitchen_evidence, delivery_snapshots, order_id, version_id = (
        _ready_released_order()
    )
    delivery_snapshots._by_version.clear()
    seed_delivery_snapshot(
        delivery_snapshots,
        order_id=order_id,
        order_version_id=version_id,
        fulfillment_mode="PICKUP",
        delivery_address=None,
    )
    KitchenExecutionService(
        orders,
        kitchen_evidence,
        clock=lambda: _NOW,
    ).record_kitchen_completion(
        order_id,
        version_id,
        completed_at=_NOW,
        recorded_by="kitchen-panel",
        evidence_reference="ticket-42",
    )

    assert order_id not in _delivery_queue_order_ids(
        orders,
        kitchen_evidence,
        delivery_snapshots,
    )


def test_delivery_queue_projection_ignores_live_offer_mutations() -> None:
    offer, version_id, variant_id, acceptance_id, offers, orders, _inq, service = (
        _accepted_offer_state()
    )
    _converted, order, order_version = service.convert_accepted_offer(
        offer.offer_id,
        version_id,
        variant_id,
        acceptance_id,
    )
    delivery_snapshots = InMemoryOrderDeliverySnapshotRepository()
    seed_delivery_snapshot(
        delivery_snapshots,
        order_id=order.order_id,
        order_version_id=order_version.order_version_id,
        location_text=order_version.location_text,
        time_window_text=order_version.time_window_text,
    )
    kitchen_evidence = InMemoryKitchenCompletionEvidenceRepository()
    core = OperationalCoreService(orders)
    core.confirm_kitchen_print(order.order_id, order_version.order_version_id)
    core.make_order_version_effective(order.order_id, order_version.order_version_id)
    KitchenExecutionService(
        orders,
        kitchen_evidence,
        clock=lambda: _NOW,
    ).record_kitchen_completion(
        order.order_id,
        order_version.order_version_id,
        completed_at=_NOW,
        recorded_by="kitchen-panel",
        evidence_reference="ticket-42",
    )

    stored = offers.get(offer.offer_id)
    assert stored is not None
    version = stored.versions[0]
    variant = version.variants[0]
    offers._offers[stored.offer_id] = replace(
        stored,
        versions=(
            replace(
                version,
                variants=(
                    replace(
                        variant,
                        positions=(
                            replace(variant.positions[0], name="MUTATED LIVE OFFER"),
                        ),
                    ),
                ),
            ),
        ),
    )

    entry = build_delivery_queue_projection(
        orders,
        kitchen_evidence,
        delivery_snapshots,
    )[0]
    assert entry.delivery_snapshot.location_text == "Hamburg"
    assert "MUTATED LIVE OFFER" not in entry.delivery_snapshot.location_text


def test_delivery_queue_contract_must_not_depend_on_offer_inquiry_or_configurator() -> (
    None
):
    helpers_root = Path(__file__).resolve().parents[1] / "helpers"
    forbidden = (
        "OfferRepository",
        "offer_repository",
        "Configurator",
        "configurator",
        "InquiryRepository",
        "inquiry_repository",
        "OrderCommercialSnapshot",
    )
    for name in ("delivery_queue_contract.py", "delivery_snapshot_contract.py"):
        text = (helpers_root / name).read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in text, f"{name}: {token}"

    services_root = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "catering_system"
        / "services"
    )
    production_module = services_root / "delivery_queue_projection_service.py"
    if production_module.exists():
        production_text = production_module.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in production_text, production_module.name
