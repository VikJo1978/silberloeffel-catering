"""Unit tests — KitchenExecutionService completion evidence."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from catering_system.domain.ready_to_send import READY_REASON_NO_EFFECTIVE_VERSION
from catering_system.repositories.in_memory_kitchen_completion_evidence_repository import (
    InMemoryKitchenCompletionEvidenceRepository,
)
from catering_system.repositories.in_memory_order_commercial_snapshot_repository import (
    InMemoryOrderCommercialSnapshotRepository,
)
from catering_system.repositories.in_memory_order_repository import (
    InMemoryOrderRepository,
)
from catering_system.services.kitchen_execution_service import (
    KitchenCompletionBlockedError,
    KitchenCompletionConflictError,
    KitchenExecutionService,
)
from catering_system.services.kitchen_queue_projection_service import (
    KitchenQueueProjectionService,
)
from catering_system.services.operational_core_service import OperationalCoreService
from tests.helpers.commercial_snapshot_seed import seed_commercial_snapshot
from tests.helpers.order_seed import seed_order
from tests.unit.test_offer_service import _accepted_offer_state, _sample_inquiry

_NOW = datetime(2026, 8, 7, 9, 0, tzinfo=UTC)


def _ready_order() -> tuple[
    InMemoryOrderRepository,
    InMemoryOrderCommercialSnapshotRepository,
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
    snapshots = service._commercial_snapshots
    core = OperationalCoreService(orders)
    core.confirm_kitchen_print(order.order_id, order_version.order_version_id)
    core.make_order_version_effective(order.order_id, order_version.order_version_id)
    assert core.evaluate_ready_to_send(order.order_id).ready is True
    return orders, snapshots, order.order_id, order_version.order_version_id


def test_record_kitchen_completion_persists_append_only_evidence() -> None:
    orders, _snapshots, order_id, version_id = _ready_order()
    evidence_repo = InMemoryKitchenCompletionEvidenceRepository()
    service = KitchenExecutionService(
        orders,
        evidence_repo,
        clock=lambda: _NOW,
    )

    result = service.record_kitchen_completion(
        order_id,
        version_id,
        completed_at=_NOW,
        recorded_by="kitchen-panel",
        evidence_reference="ticket-42",
    )
    assert result.replay is False
    stored = evidence_repo.get_by_order_version_id(order_id, version_id)
    assert stored == result.evidence


def test_record_kitchen_completion_replay_is_idempotent() -> None:
    orders, _snapshots, order_id, version_id = _ready_order()
    evidence_repo = InMemoryKitchenCompletionEvidenceRepository()
    service = KitchenExecutionService(
        orders,
        evidence_repo,
        clock=lambda: _NOW,
    )
    first = service.record_kitchen_completion(
        order_id,
        version_id,
        completed_at=_NOW,
        recorded_by="kitchen-panel",
        evidence_reference="ticket-42",
    )
    second = service.record_kitchen_completion(
        order_id,
        version_id,
        completed_at=_NOW,
        recorded_by="kitchen-panel",
        evidence_reference="ticket-42",
    )
    assert first.evidence == second.evidence
    assert second.replay is True


def test_record_kitchen_completion_rejects_conflicting_replay() -> None:
    orders, _snapshots, order_id, version_id = _ready_order()
    evidence_repo = InMemoryKitchenCompletionEvidenceRepository()
    service = KitchenExecutionService(
        orders,
        evidence_repo,
        clock=lambda: _NOW,
    )
    service.record_kitchen_completion(
        order_id,
        version_id,
        completed_at=_NOW,
        recorded_by="kitchen-panel",
        evidence_reference="ticket-42",
    )
    with pytest.raises(KitchenCompletionConflictError):
        service.record_kitchen_completion(
            order_id,
            version_id,
            completed_at=_NOW,
            recorded_by="kitchen-panel",
            evidence_reference="ticket-99",
        )


def test_record_kitchen_completion_blocked_when_not_ready() -> None:
    orders = InMemoryOrderRepository()
    snapshots = InMemoryOrderCommercialSnapshotRepository()
    order, version = seed_order(orders, _sample_inquiry())
    seed_commercial_snapshot(snapshots, order.order_id)
    service = KitchenExecutionService(orders, InMemoryKitchenCompletionEvidenceRepository())

    with pytest.raises(KitchenCompletionBlockedError) as exc_info:
        service.record_kitchen_completion(
            order.order_id,
            version.order_version_id,
            completed_at=_NOW,
            recorded_by="kitchen-panel",
            evidence_reference="ticket-1",
        )
    assert exc_info.value.reasons == (READY_REASON_NO_EFFECTIVE_VERSION,)


def test_kitchen_queue_and_completion_do_not_mutate_order_version() -> None:
    orders, snapshots, order_id, version_id = _ready_order()
    before = orders.get_order_version(version_id)
    assert before is not None

    queue = KitchenQueueProjectionService(orders, snapshots).list_queue()
    assert len(queue) == 1

    KitchenExecutionService(
        orders,
        InMemoryKitchenCompletionEvidenceRepository(),
        clock=lambda: _NOW,
    ).record_kitchen_completion(
        order_id,
        version_id,
        completed_at=_NOW,
        recorded_by="kitchen-panel",
        evidence_reference="ticket-42",
    )

    after = orders.get_order_version(version_id)
    assert after == before


def test_kitchen_execution_services_must_not_depend_on_offer_or_catalog() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "src" / "catering_system" / "services"
    for name in (
        "kitchen_queue_projection_service.py",
        "kitchen_execution_service.py",
    ):
        text = (root / name).read_text(encoding="utf-8")
        assert "OfferRepository" not in text, name
        assert "offer_repository" not in text, name
        assert "CatalogRepository" not in text, name
