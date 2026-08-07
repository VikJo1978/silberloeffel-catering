"""Unit tests — DeliveryExecutionService dispatch and completion evidence."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from catering_system.repositories.in_memory_delivery_completion_evidence_repository import (
    InMemoryDeliveryCompletionEvidenceRepository,
)
from catering_system.repositories.in_memory_dispatch_evidence_repository import (
    InMemoryDispatchEvidenceRepository,
)
from catering_system.repositories.in_memory_kitchen_completion_evidence_repository import (
    InMemoryKitchenCompletionEvidenceRepository,
)
from catering_system.repositories.in_memory_order_commercial_snapshot_repository import (
    InMemoryOrderCommercialSnapshotRepository,
)
from catering_system.repositories.in_memory_order_delivery_snapshot_repository import (
    InMemoryOrderDeliverySnapshotRepository,
)
from catering_system.repositories.in_memory_order_repository import (
    InMemoryOrderRepository,
)
from catering_system.services.delivery_execution_service import (
    DeliveryEvidenceConflictError,
    DeliveryExecutionBlockedError,
    DeliveryExecutionService,
)
from catering_system.services.delivery_queue_projection_service import (
    DeliveryQueueProjectionService,
)
from catering_system.services.kitchen_execution_service import KitchenExecutionService
from catering_system.services.operational_core_service import OperationalCoreService
from tests.helpers.delivery_snapshot_contract import seed_delivery_snapshot
from tests.unit.test_offer_service import _accepted_offer_state

_NOW = datetime(2026, 8, 7, 15, 0, tzinfo=UTC)
_COMPLETED_AT = datetime(2026, 8, 7, 16, 0, tzinfo=UTC)


def _delivery_eligible_order() -> tuple[
    InMemoryOrderRepository,
    InMemoryKitchenCompletionEvidenceRepository,
    InMemoryOrderDeliverySnapshotRepository,
    InMemoryDispatchEvidenceRepository,
    InMemoryDeliveryCompletionEvidenceRepository,
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
    core = OperationalCoreService(orders)
    core.confirm_kitchen_print(order.order_id, order_version.order_version_id)
    core.make_order_version_effective(order.order_id, order_version.order_version_id)

    delivery_snapshots = InMemoryOrderDeliverySnapshotRepository()
    seed_delivery_snapshot(
        delivery_snapshots,
        order_id=order.order_id,
        order_version_id=order_version.order_version_id,
        time_window_text=order_version.time_window_text,
        location_text=order_version.location_text,
    )
    kitchen_evidence = InMemoryKitchenCompletionEvidenceRepository()
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
    return (
        orders,
        kitchen_evidence,
        delivery_snapshots,
        InMemoryDispatchEvidenceRepository(),
        InMemoryDeliveryCompletionEvidenceRepository(),
        order.order_id,
        order_version.order_version_id,
    )


def _service(
    orders: InMemoryOrderRepository,
    kitchen_evidence: InMemoryKitchenCompletionEvidenceRepository,
    delivery_snapshots: InMemoryOrderDeliverySnapshotRepository,
    dispatch_repo: InMemoryDispatchEvidenceRepository,
    completion_repo: InMemoryDeliveryCompletionEvidenceRepository,
) -> DeliveryExecutionService:
    return DeliveryExecutionService(
        orders,
        kitchen_evidence,
        delivery_snapshots,
        dispatch_repo,
        completion_repo,
        clock=lambda: _NOW,
    )


def test_record_dispatch_persists_append_only_evidence() -> None:
    (
        orders,
        kitchen_evidence,
        delivery_snapshots,
        dispatch_repo,
        completion_repo,
        order_id,
        version_id,
    ) = _delivery_eligible_order()
    service = _service(
        orders,
        kitchen_evidence,
        delivery_snapshots,
        dispatch_repo,
        completion_repo,
    )

    result = service.record_dispatch(
        order_id,
        version_id,
        dispatched_at=_NOW,
        recorded_by="office-dispatch",
        evidence_reference="dispatch-77",
    )
    assert result.replay is False
    stored = dispatch_repo.get_by_order_version_id(order_id, version_id)
    assert stored == result.evidence


def test_record_dispatch_replay_is_idempotent() -> None:
    (
        orders,
        kitchen_evidence,
        delivery_snapshots,
        dispatch_repo,
        completion_repo,
        order_id,
        version_id,
    ) = _delivery_eligible_order()
    service = _service(
        orders,
        kitchen_evidence,
        delivery_snapshots,
        dispatch_repo,
        completion_repo,
    )
    first = service.record_dispatch(
        order_id,
        version_id,
        dispatched_at=_NOW,
        recorded_by="office-dispatch",
        evidence_reference="dispatch-77",
    )
    second = service.record_dispatch(
        order_id,
        version_id,
        dispatched_at=_NOW,
        recorded_by="office-dispatch",
        evidence_reference="dispatch-77",
    )
    assert first.evidence == second.evidence
    assert second.replay is True


def test_record_dispatch_rejects_conflicting_replay() -> None:
    (
        orders,
        kitchen_evidence,
        delivery_snapshots,
        dispatch_repo,
        completion_repo,
        order_id,
        version_id,
    ) = _delivery_eligible_order()
    service = _service(
        orders,
        kitchen_evidence,
        delivery_snapshots,
        dispatch_repo,
        completion_repo,
    )
    service.record_dispatch(
        order_id,
        version_id,
        dispatched_at=_NOW,
        recorded_by="office-dispatch",
        evidence_reference="dispatch-77",
    )
    with pytest.raises(DeliveryEvidenceConflictError):
        service.record_dispatch(
            order_id,
            version_id,
            dispatched_at=_NOW,
            recorded_by="office-dispatch",
            evidence_reference="dispatch-99",
        )


def test_record_dispatch_blocked_without_kitchen_completion() -> None:
    offer, version_id, variant_id, acceptance_id, _offers, orders, _inq, service = (
        _accepted_offer_state()
    )
    _converted, order, order_version = service.convert_accepted_offer(
        offer.offer_id,
        version_id,
        variant_id,
        acceptance_id,
    )
    core = OperationalCoreService(orders)
    core.confirm_kitchen_print(order.order_id, order_version.order_version_id)
    core.make_order_version_effective(order.order_id, order_version.order_version_id)

    delivery_snapshots = InMemoryOrderDeliverySnapshotRepository()
    seed_delivery_snapshot(
        delivery_snapshots,
        order_id=order.order_id,
        order_version_id=order_version.order_version_id,
    )
    dispatch_repo = InMemoryDispatchEvidenceRepository()
    service = _service(
        orders,
        InMemoryKitchenCompletionEvidenceRepository(),
        delivery_snapshots,
        dispatch_repo,
        InMemoryDeliveryCompletionEvidenceRepository(),
    )

    with pytest.raises(DeliveryExecutionBlockedError):
        service.record_dispatch(
            order.order_id,
            order_version.order_version_id,
            dispatched_at=_NOW,
            recorded_by="office-dispatch",
            evidence_reference="dispatch-77",
        )


def test_record_delivery_completion_requires_dispatch() -> None:
    (
        orders,
        kitchen_evidence,
        delivery_snapshots,
        dispatch_repo,
        completion_repo,
        order_id,
        version_id,
    ) = _delivery_eligible_order()
    service = _service(
        orders,
        kitchen_evidence,
        delivery_snapshots,
        dispatch_repo,
        completion_repo,
    )

    with pytest.raises(DeliveryExecutionBlockedError):
        service.record_delivery_completion(
            order_id,
            version_id,
            completed_at=_COMPLETED_AT,
            recorded_by="office-dispatch",
            evidence_reference="delivered-88",
        )


def test_record_delivery_completion_replay_is_idempotent() -> None:
    (
        orders,
        kitchen_evidence,
        delivery_snapshots,
        dispatch_repo,
        completion_repo,
        order_id,
        version_id,
    ) = _delivery_eligible_order()
    service = _service(
        orders,
        kitchen_evidence,
        delivery_snapshots,
        dispatch_repo,
        completion_repo,
    )
    service.record_dispatch(
        order_id,
        version_id,
        dispatched_at=_NOW,
        recorded_by="office-dispatch",
        evidence_reference="dispatch-77",
    )
    first = service.record_delivery_completion(
        order_id,
        version_id,
        completed_at=_COMPLETED_AT,
        recorded_by="office-dispatch",
        evidence_reference="delivered-88",
    )
    second = service.record_delivery_completion(
        order_id,
        version_id,
        completed_at=_COMPLETED_AT,
        recorded_by="office-dispatch",
        evidence_reference="delivered-88",
    )
    assert first.evidence == second.evidence
    assert second.replay is True


def test_delivery_queue_and_evidence_do_not_mutate_order_version() -> None:
    (
        orders,
        kitchen_evidence,
        delivery_snapshots,
        dispatch_repo,
        completion_repo,
        order_id,
        version_id,
    ) = _delivery_eligible_order()
    before = orders.get_order_version(version_id)
    assert before is not None

    queue = DeliveryQueueProjectionService(
        orders,
        kitchen_evidence,
        delivery_snapshots,
    ).list_queue()
    assert len(queue) == 1

    service = _service(
        orders,
        kitchen_evidence,
        delivery_snapshots,
        dispatch_repo,
        completion_repo,
    )
    service.record_dispatch(
        order_id,
        version_id,
        dispatched_at=_NOW,
        recorded_by="office-dispatch",
        evidence_reference="dispatch-77",
    )
    service.record_delivery_completion(
        order_id,
        version_id,
        completed_at=_COMPLETED_AT,
        recorded_by="office-dispatch",
        evidence_reference="delivered-88",
    )

    after = orders.get_order_version(version_id)
    assert after == before


def test_delivery_execution_services_must_not_depend_on_offer_or_catalog() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "src" / "catering_system" / "services"
    for name in (
        "delivery_queue_projection_service.py",
        "delivery_execution_service.py",
    ):
        text = (root / name).read_text(encoding="utf-8")
        assert "OfferRepository" not in text, name
        assert "offer_repository" not in text, name
        assert "CatalogRepository" not in text, name
