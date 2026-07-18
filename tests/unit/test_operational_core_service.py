"""Unit tests — operational core (OPERATIONAL_CORE_EXECUTION_PACK_V1 §14/§15)."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import date, datetime, timezone

import pytest

from catering_system.domain.inquiry import (
    CALL_VERIFICATION_STATUSES,
    CRM_PIPELINE,
    Inquiry,
    PLANNING_MODES,
)
from catering_system.domain.operational_core_events import (
    KitchenPrintConfirmed,
    OrderReadyToSend,
    OrderReadyToSendBlocked,
    OrderVersionMadeEffective,
)
from catering_system.domain.ready_to_send import (
    READY_REASON_KITCHEN_PRINT_NOT_CONFIRMED,
    READY_REASON_NO_EFFECTIVE_VERSION,
    READY_REASON_ORDER_NOT_FOUND,
)
from catering_system.repositories.in_memory_order_repository import (
    InMemoryOrderRepository,
)
from catering_system.services.operational_core_service import OperationalCoreService
from catering_system.services.order_service import OrderService


def _sample_inquiry() -> Inquiry:
    now = datetime.now(timezone.utc)
    return Inquiry(
        inquiry_id="11111111-1111-1111-1111-111111111111",
        event_date=date(2026, 10, 1),
        created_at=now,
        updated_at=now,
        inquiry_source="manual",
        crm_stage=CRM_PIPELINE[0],
        customer_linkage={},
        time_window_text="mittags",
        location_text="Hamburg",
        guest_count_estimate=25,
        planning_mode=PLANNING_MODES[0],
        call_verification_required=False,
        call_verification_status=CALL_VERIFICATION_STATUSES[0],
    )


def _setup() -> tuple[
    InMemoryOrderRepository, OrderService, OperationalCoreService, list[object]
]:
    repo = InMemoryOrderRepository()
    events: list[object] = []
    return (
        repo,
        OrderService(repo),
        OperationalCoreService(repo, event_sink=events.append),
        events,
    )


def test_confirm_kitchen_print_sets_timestamp_and_emits() -> None:
    repo, osvc, core, events = _setup()
    order, v1 = osvc.convert_inquiry_to_order(_sample_inquiry())
    confirmed = core.confirm_kitchen_print(order.order_id, v1.order_version_id)
    assert confirmed.kitchen_print_confirmed_at is not None
    stored = repo.get_order_version(v1.order_version_id)
    assert stored is not None and stored.kitchen_print_confirmed_at is not None
    assert events == [
        KitchenPrintConfirmed(
            order_id=order.order_id, order_version_id=v1.order_version_id
        )
    ]


def test_confirm_kitchen_print_is_idempotent() -> None:
    _repo, osvc, core, events = _setup()
    order, v1 = osvc.convert_inquiry_to_order(_sample_inquiry())
    first = core.confirm_kitchen_print(order.order_id, v1.order_version_id)
    second = core.confirm_kitchen_print(order.order_id, v1.order_version_id)
    assert second == first  # same timestamp, no re-stamp
    assert len(events) == 1  # no duplicate event


def test_confirm_kitchen_print_rejects_foreign_or_unknown_version() -> None:
    _repo, osvc, core, _events = _setup()
    order_a, _va = osvc.convert_inquiry_to_order(_sample_inquiry())
    order_b, vb = osvc.convert_inquiry_to_order(_sample_inquiry())
    with pytest.raises(ValueError):
        core.confirm_kitchen_print(order_a.order_id, vb.order_version_id)
    with pytest.raises(ValueError):
        core.confirm_kitchen_print(order_a.order_id, "missing-version")
    with pytest.raises(ValueError):
        core.confirm_kitchen_print("missing-order", vb.order_version_id)


def test_make_effective_blocked_without_kitchen_print() -> None:
    repo, osvc, core, events = _setup()
    order, v1 = osvc.convert_inquiry_to_order(_sample_inquiry())
    with pytest.raises(ValueError, match="kitchen print not confirmed"):
        core.make_order_version_effective(order.order_id, v1.order_version_id)
    stored = repo.get_order(order.order_id)
    assert stored is not None and stored.effective_order_version_id is None
    assert events == []


def test_make_effective_succeeds_after_confirmation() -> None:
    repo, osvc, core, events = _setup()
    order, v1 = osvc.convert_inquiry_to_order(_sample_inquiry())
    core.confirm_kitchen_print(order.order_id, v1.order_version_id)
    updated = core.make_order_version_effective(order.order_id, v1.order_version_id)
    assert updated.effective_order_version_id == v1.order_version_id
    stored = repo.get_order(order.order_id)
    assert (
        stored is not None and stored.effective_order_version_id == v1.order_version_id
    )
    assert events[-1] == OrderVersionMadeEffective(
        order_id=order.order_id, order_version_id=v1.order_version_id
    )


def test_make_effective_clears_current_candidate() -> None:
    repo, osvc, core, _events = _setup()
    order, v1 = osvc.convert_inquiry_to_order(_sample_inquiry())
    core.confirm_kitchen_print(order.order_id, v1.order_version_id)
    core.make_order_version_effective(order.order_id, v1.order_version_id)
    v2 = osvc.propose_order_version_change(
        order.order_id,
        event_date=date(2026, 10, 2),
        time_window_text="abends",
        location_text="Hamburg",
        guest_count_estimate=30,
        planning_mode=PLANNING_MODES[0],
        actor_reference="office-panel",
        change_reason="Neue Gästezahl",
    )
    core.confirm_kitchen_print(order.order_id, v2.order_version_id)
    core.make_order_version_effective(order.order_id, v2.order_version_id)
    stored = repo.get_order(order.order_id)
    assert stored is not None
    assert stored.candidate_order_version_id is None
    assert stored.effective_order_version_id == v2.order_version_id


def test_make_effective_rejects_non_candidate_version() -> None:
    _repo, osvc, core, _events = _setup()
    order, v1 = osvc.convert_inquiry_to_order(_sample_inquiry())
    v2 = osvc.create_relevant_order_change_version(
        order,
        event_date=date(2026, 10, 2),
        time_window_text="abends",
        location_text="Hamburg",
        guest_count_estimate=30,
        planning_mode=PLANNING_MODES[0],
    )
    osvc.set_candidate_order_version(order.order_id, v2.order_version_id)
    core.confirm_kitchen_print(order.order_id, v1.order_version_id)
    with pytest.raises(ValueError, match="not current candidate"):
        core.make_order_version_effective(order.order_id, v1.order_version_id)


def test_history_immutable_after_switch() -> None:
    repo, osvc, core, _events = _setup()
    order, v1 = osvc.convert_inquiry_to_order(_sample_inquiry())
    v2 = osvc.create_relevant_order_change_version(
        order,
        event_date=date(2026, 10, 2),
        time_window_text="abends",
        location_text="Hamburg",
        guest_count_estimate=30,
        planning_mode=PLANNING_MODES[0],
    )
    before = repo.list_order_versions(order.order_id)
    core.confirm_kitchen_print(order.order_id, v2.order_version_id)
    core.make_order_version_effective(order.order_id, v2.order_version_id)
    after = repo.list_order_versions(order.order_id)
    assert [v.order_version_id for v in after] == [v.order_version_id for v in before]
    assert [v.version_number for v in after] == [1, 2]
    # v1 row untouched by the switch
    assert after[0] == before[0] == v1


def test_confirming_old_version_does_not_affect_current_effective() -> None:
    repo, osvc, core, _events = _setup()
    order, v1 = osvc.convert_inquiry_to_order(_sample_inquiry())
    v2 = osvc.create_relevant_order_change_version(
        order,
        event_date=date(2026, 10, 2),
        time_window_text="abends",
        location_text="Hamburg",
        guest_count_estimate=30,
        planning_mode=PLANNING_MODES[0],
    )
    core.confirm_kitchen_print(order.order_id, v2.order_version_id)
    core.make_order_version_effective(order.order_id, v2.order_version_id)
    core.confirm_kitchen_print(order.order_id, v1.order_version_id)  # old version
    stored = repo.get_order(order.order_id)
    assert (
        stored is not None and stored.effective_order_version_id == v2.order_version_id
    )


def test_ready_to_send_unknown_order_blocked() -> None:
    _repo, _osvc, core, _events = _setup()
    ev = core.evaluate_ready_to_send("00000000-0000-0000-0000-000000000000")
    assert ev.ready is False
    assert ev.reasons == (READY_REASON_ORDER_NOT_FOUND,)
    assert ev.order_id == "00000000-0000-0000-0000-000000000000"


def test_ready_to_send_blocked_without_effective_version() -> None:
    _repo, osvc, core, _events = _setup()
    order, _v1 = osvc.convert_inquiry_to_order(_sample_inquiry())
    ev = core.evaluate_ready_to_send(order.order_id)
    assert ev.ready is False
    assert ev.reasons == (READY_REASON_NO_EFFECTIVE_VERSION,)


def test_ready_to_send_ready_after_confirm_and_switch() -> None:
    _repo, osvc, core, _events = _setup()
    order, v1 = osvc.convert_inquiry_to_order(_sample_inquiry())
    core.confirm_kitchen_print(order.order_id, v1.order_version_id)
    core.make_order_version_effective(order.order_id, v1.order_version_id)
    ev = core.evaluate_ready_to_send(order.order_id)
    assert ev.ready is True
    assert ev.reasons == ()


def test_evaluate_ready_to_send_is_pure() -> None:
    repo, osvc, core, events = _setup()
    order, _v1 = osvc.convert_inquiry_to_order(_sample_inquiry())
    before_order = repo.get_order(order.order_id)
    core.evaluate_ready_to_send(order.order_id)
    assert repo.get_order(order.order_id) == before_order
    assert events == []  # pure read emits nothing


def test_request_ready_to_send_emits_blocked_and_changes_nothing() -> None:
    repo, osvc, core, events = _setup()
    order, _v1 = osvc.convert_inquiry_to_order(_sample_inquiry())
    before_order = repo.get_order(order.order_id)
    ev = core.request_ready_to_send(order.order_id)
    assert ev.ready is False
    assert events == [
        OrderReadyToSendBlocked(
            order_id=order.order_id, reasons=(READY_REASON_NO_EFFECTIVE_VERSION,)
        )
    ]
    assert repo.get_order(order.order_id) == before_order  # no truth change


def test_request_ready_to_send_emits_success() -> None:
    _repo, osvc, core, events = _setup()
    order, v1 = osvc.convert_inquiry_to_order(_sample_inquiry())
    core.confirm_kitchen_print(order.order_id, v1.order_version_id)
    core.make_order_version_effective(order.order_id, v1.order_version_id)
    ev = core.request_ready_to_send(order.order_id)
    assert ev.ready is True
    assert events[-1] == OrderReadyToSend(order_id=order.order_id)


def test_ready_reason_when_effective_set_but_print_missing_is_unreachable_via_service() -> (
    None
):
    """The service gate makes KITCHEN_PRINT_NOT_CONFIRMED unreachable through commands;
    the domain rule still covers it for defense in depth."""
    from catering_system.domain.ready_to_send import evaluate_ready_to_send_from_facts

    _repo, osvc, _core, _events = _setup()
    order, v1 = osvc.convert_inquiry_to_order(_sample_inquiry())
    from dataclasses import replace

    tampered = replace(order, effective_order_version_id=v1.order_version_id)
    ev = evaluate_ready_to_send_from_facts(tampered, v1)
    assert ev.ready is False
    assert ev.reasons == (READY_REASON_KITCHEN_PRINT_NOT_CONFIRMED,)


def test_order_and_version_are_frozen() -> None:
    _repo, osvc, _core, _events = _setup()
    order, v1 = osvc.convert_inquiry_to_order(_sample_inquiry())
    with pytest.raises(FrozenInstanceError):
        order.effective_order_version_id = v1.order_version_id  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        v1.guest_count_estimate = 999  # type: ignore[misc]
