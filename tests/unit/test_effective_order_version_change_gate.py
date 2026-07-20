"""EFFECTIVE_ORDER_VERSION_CHANGE_GATE_V1 focused Core regressions."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone

import pytest

from catering_system.domain.inquiry import Inquiry
from catering_system.domain.operational_core_events import (
    OrderVersionCandidateSuperseded,
    OrderVersionChangeProposed,
)
from catering_system.domain.order import is_order_version_superseded
from catering_system.domain.ready_to_send import (
    READY_REASON_PENDING_ORDER_VERSION_CHANGE,
)
from catering_system.repositories.in_memory_order_repository import (
    InMemoryOrderRepository,
)
from catering_system.services.operational_core_service import OperationalCoreService
from catering_system.services.order_service import OrderService

from catering_system.domain.inquiry_customer_snapshot import (
    InquiryCustomerSnapshot as _CCSnapshot,
)

_CONTACT_COMPLETE_SNAPSHOT = _CCSnapshot(
    email="kunde@example.com", phone="+49301234567"
)


def _inquiry() -> Inquiry:
    now = datetime.now(timezone.utc)
    return Inquiry(
        inquiry_id="11111111-1111-4111-8111-111111111111",
        event_date=date(2026, 10, 1),
        created_at=now,
        updated_at=now,
        inquiry_source="manual",
        crm_stage="Neue Anfrage",
        customer_linkage={},
        time_window_text="mittags",
        location_text="Hamburg",
        guest_count_estimate=25,
        planning_mode="caterer_suggestion",
        call_verification_required=False,
        call_verification_status="not_required",
        customer_snapshot=_CONTACT_COMPLETE_SNAPSHOT,
    )


def _effective_v1():  # noqa: ANN202
    repository = InMemoryOrderRepository()
    events: list[object] = []
    orders = OrderService(repository, event_sink=events.append)
    core = OperationalCoreService(repository)
    order, version = orders.convert_inquiry_to_order(_inquiry())
    core.confirm_kitchen_print(order.order_id, version.order_version_id)
    core.make_order_version_effective(order.order_id, version.order_version_id)
    return repository, orders, core, events, order, version


def test_change_is_immutable_candidate_and_blocks_ready_until_switch() -> None:
    repository, orders, core, events, order, v1 = _effective_v1()
    frozen_v1 = repository.get_order_version(v1.order_version_id)
    v2 = orders.propose_order_version_change(
        order.order_id,
        event_date=date(2026, 10, 2),
        time_window_text=v1.time_window_text,
        location_text=v1.location_text,
        guest_count_estimate=v1.guest_count_estimate,
        planning_mode=v1.planning_mode,
        actor_reference="office-panel",
        change_reason="Termin verschoben",
    )

    stored_order = repository.get_order(order.order_id)
    assert stored_order is not None
    assert repository.get_order_version(v1.order_version_id) == frozen_v1
    assert stored_order.effective_order_version_id == v1.order_version_id
    assert stored_order.candidate_order_version_id == v2.order_version_id
    assert v2.parent_order_version_id == v1.order_version_id
    assert v2.created_by == "office-panel"
    assert v2.change_reason == "Termin verschoben"
    assert v2.changed_fields == ("event_date",)
    assert v2.kitchen_print_confirmed_at is None
    proposed = events[-1]
    assert isinstance(proposed, OrderVersionChangeProposed)
    assert proposed.changed_fields == ("event_date",)
    assert core.evaluate_ready_to_send(order.order_id).reasons == (
        READY_REASON_PENDING_ORDER_VERSION_CHANGE,
    )

    with pytest.raises(ValueError, match="kitchen print not confirmed"):
        core.make_order_version_effective(order.order_id, v2.order_version_id)
    core.confirm_kitchen_print(order.order_id, v2.order_version_id)
    assert core.evaluate_ready_to_send(order.order_id).reasons == (
        READY_REASON_PENDING_ORDER_VERSION_CHANGE,
    )
    switched = core.make_order_version_effective(order.order_id, v2.order_version_id)
    assert switched.effective_order_version_id == v2.order_version_id
    assert switched.candidate_order_version_id is None
    assert core.evaluate_ready_to_send(order.order_id).ready is True


def test_second_edit_supersedes_first_candidate_without_mutating_it() -> None:
    repository, orders, core, events, order, v1 = _effective_v1()
    v2 = orders.propose_order_version_change(
        order.order_id,
        event_date=v1.event_date,
        time_window_text="14:00",
        location_text=v1.location_text,
        guest_count_estimate=v1.guest_count_estimate,
        planning_mode=v1.planning_mode,
        actor_reference="office-panel",
        change_reason="Neue Uhrzeit",
    )
    frozen_v2 = repository.get_order_version(v2.order_version_id)
    v3 = orders.propose_order_version_change(
        order.order_id,
        event_date=v1.event_date,
        time_window_text="15:00",
        location_text=v1.location_text,
        guest_count_estimate=v1.guest_count_estimate,
        planning_mode=v1.planning_mode,
        actor_reference="office-panel",
        change_reason="Nochmals verschoben",
    )

    stored_order = repository.get_order(order.order_id)
    versions = repository.list_order_versions(order.order_id)
    assert stored_order is not None
    assert repository.get_order_version(v2.order_version_id) == frozen_v2
    assert stored_order.effective_order_version_id == v1.order_version_id
    assert stored_order.candidate_order_version_id == v3.order_version_id
    assert is_order_version_superseded(stored_order, v2, versions)
    assert any(isinstance(event, OrderVersionCandidateSuperseded) for event in events)
    core.confirm_kitchen_print(order.order_id, v2.order_version_id)
    with pytest.raises(ValueError, match="not current candidate"):
        core.make_order_version_effective(order.order_id, v2.order_version_id)


def test_repository_allows_only_additive_confirmation_fact() -> None:
    repository, _orders, core, _events, order, v1 = _effective_v1()
    stored = repository.get_order_version(v1.order_version_id)
    assert stored is not None
    with pytest.raises(ValueError, match="snapshot is immutable"):
        repository.update_order_version(replace(stored, location_text="Kiel"))
    confirmed = core.confirm_kitchen_print(order.order_id, v1.order_version_id)
    assert confirmed.kitchen_print_confirmed_at is not None
