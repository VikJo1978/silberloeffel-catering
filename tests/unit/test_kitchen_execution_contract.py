"""Slice 5 contract tests — Kitchen Execution boundary (docs-only PR B).

Proves READY_TO_SEND eligibility drives kitchen queue membership and that queue
payload comes from OrderPrintProjection only. No domain/service/API changes.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path

from catering_system.domain.ready_to_send import (
    READY_REASON_KITCHEN_PRINT_NOT_CONFIRMED,
    READY_REASON_NO_EFFECTIVE_VERSION,
    READY_REASON_PENDING_ORDER_VERSION_CHANGE,
)
from catering_system.repositories.in_memory_order_commercial_snapshot_repository import (
    InMemoryOrderCommercialSnapshotRepository,
)
from catering_system.repositories.in_memory_order_repository import (
    InMemoryOrderRepository,
)
from catering_system.services.operational_core_service import OperationalCoreService
from catering_system.services.order_service import OrderService
from catering_system.ui.office_panel_views import render_print_sheet
from tests.helpers.commercial_snapshot_seed import seed_commercial_snapshot
from tests.helpers.kitchen_queue_contract import build_kitchen_queue_projection
from tests.helpers.order_seed import seed_order
from tests.unit.test_effective_order_version_change_gate import _effective_v1
from tests.unit.test_offer_service import _accepted_offer_state, _sample_inquiry


def _queue_order_ids(
    orders: InMemoryOrderRepository,
    snapshots: InMemoryOrderCommercialSnapshotRepository,
) -> set[str]:
    return {entry.order_id for entry in build_kitchen_queue_projection(orders, snapshots)}


def test_kitchen_queue_excludes_order_without_effective_version() -> None:
    orders = InMemoryOrderRepository()
    snapshots = InMemoryOrderCommercialSnapshotRepository()
    order, _version = seed_order(orders, _sample_inquiry())
    seed_commercial_snapshot(snapshots, order.order_id)

    core = OperationalCoreService(orders)
    evaluation = core.evaluate_ready_to_send(order.order_id)
    assert evaluation.ready is False
    assert evaluation.reasons == (READY_REASON_NO_EFFECTIVE_VERSION,)

    assert order.order_id not in _queue_order_ids(orders, snapshots)


def test_kitchen_queue_excludes_order_without_kitchen_print_confirmation() -> None:
    orders = InMemoryOrderRepository()
    snapshots = InMemoryOrderCommercialSnapshotRepository()
    order, version = seed_order(orders, _sample_inquiry())
    seed_commercial_snapshot(snapshots, order.order_id)
    orders.update_order(
        replace(order, effective_order_version_id=version.order_version_id),
    )

    core = OperationalCoreService(orders)
    evaluation = core.evaluate_ready_to_send(order.order_id)
    assert evaluation.ready is False
    assert evaluation.reasons == (READY_REASON_KITCHEN_PRINT_NOT_CONFIRMED,)

    assert order.order_id not in _queue_order_ids(orders, snapshots)


def test_kitchen_queue_excludes_order_with_pending_candidate_change() -> None:
    repository, order_service, core, _events, order, v1 = _effective_v1()
    snapshots = InMemoryOrderCommercialSnapshotRepository()
    seed_commercial_snapshot(snapshots, order.order_id)

    order_service.propose_order_version_change(
        order.order_id,
        event_date=date(2026, 10, 2),
        time_window_text=v1.time_window_text,
        location_text=v1.location_text,
        guest_count_estimate=v1.guest_count_estimate,
        planning_mode=v1.planning_mode,
        actor_reference="office-panel",
        change_reason="Termin verschoben",
    )

    evaluation = core.evaluate_ready_to_send(order.order_id)
    assert evaluation.ready is False
    assert evaluation.reasons == (READY_REASON_PENDING_ORDER_VERSION_CHANGE,)

    assert order.order_id not in _queue_order_ids(repository, snapshots)


def test_ready_order_appears_in_kitchen_queue_from_order_print_projection() -> None:
    offer, version_id, variant_id, acceptance_id, _offers, orders, _inq, service = (
        _accepted_offer_state()
    )
    _converted, order, order_version = service.convert_accepted_offer(
        offer.offer_id,
        version_id,
        variant_id,
        acceptance_id,
    )
    snapshots = service._commercial_snapshots
    core = OperationalCoreService(orders)
    core.confirm_kitchen_print(order.order_id, order_version.order_version_id)
    core.make_order_version_effective(order.order_id, order_version.order_version_id)

    assert core.evaluate_ready_to_send(order.order_id).ready is True

    queue = build_kitchen_queue_projection(orders, snapshots)
    assert len(queue) == 1
    entry = queue[0]
    assert entry.order_id == order.order_id
    assert entry.order_version_id == order_version.order_version_id
    assert entry.projection.commercial.source == "offer_conversion"
    assert entry.projection.commercial.positions[0].name == "Fingerfood Paket"
    assert render_print_sheet(entry.projection)


def test_kitchen_queue_projection_ignores_live_offer_mutations() -> None:
    offer, version_id, variant_id, acceptance_id, offers, orders, _inq, service = (
        _accepted_offer_state()
    )
    _converted, order, order_version = service.convert_accepted_offer(
        offer.offer_id,
        version_id,
        variant_id,
        acceptance_id,
    )
    snapshots = service._commercial_snapshots
    core = OperationalCoreService(orders)
    core.confirm_kitchen_print(order.order_id, order_version.order_version_id)
    core.make_order_version_effective(order.order_id, order_version.order_version_id)

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

    entry = build_kitchen_queue_projection(orders, snapshots)[0]
    assert entry.projection.commercial.positions[0].name == "Fingerfood Paket"
    assert "MUTATED LIVE OFFER" not in render_print_sheet(entry.projection)


def test_kitchen_queue_contract_must_not_depend_on_offer_or_catalog() -> None:
    contract_path = (
        Path(__file__).resolve().parents[1] / "helpers" / "kitchen_queue_contract.py"
    )
    text = contract_path.read_text(encoding="utf-8")
    forbidden = (
        "OfferRepository",
        "offer_repository",
        "conversion_link",
        "Configurator",
        "catalog_repository",
        "CatalogRepository",
    )
    for token in forbidden:
        assert token not in text, token

    services_root = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "catering_system"
        / "services"
    )
    production_module = services_root / "kitchen_queue_projection_service.py"
    if production_module.exists():
        production_text = production_module.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in production_text, production_module.name
