"""Unit tests — Slice B7–B10 progression derived reads, view, decision, checkpoint (derived)."""

from __future__ import annotations

import sys
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from catering_system.domain.inquiry import (
    CALL_VERIFICATION_STATUSES,
    CRM_PIPELINE,
    Inquiry,
    PLANNING_MODES,
)
from catering_system.domain.order_progression_checkpoint import OrderProgressionCheckpoint
from catering_system.domain.order_progression_decision import OrderProgressionDecision
from catering_system.domain.order_progression_view import OrderProgressionView
from catering_system.domain.progression_blockers import (
    REASON_CANDIDATE_ORDER_VERSION_MISSING,
    REASON_CANDIDATE_ORDER_VERSION_NOT_RESOLVABLE,
    REASON_INQUIRY_CALL_VERIFICATION_UNSATISFIED,
    REASON_ORDER_NOT_FOUND,
    evaluate_inquiry_to_order_progression,
)
from catering_system.repositories.in_memory_order_repository import InMemoryOrderRepository
from catering_system.services.order_service import OrderService
from catering_system.services.progression_service import ProgressionService


def _module_source_lower(module: object) -> str:
    return Path(module.__file__).read_text(encoding="utf-8").lower()


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


def test_inquiry_to_order_blocked_when_verification_gate_unsatisfied() -> None:
    svc = ProgressionService(InMemoryOrderRepository())
    inquiry = replace(
        _sample_inquiry(),
        call_verification_required=True,
        call_verification_status="pending",
    )
    ev = svc.evaluate_inquiry_to_order_progression(inquiry)
    assert ev.blocked is True
    assert REASON_INQUIRY_CALL_VERIFICATION_UNSATISFIED in ev.reasons
    ev2 = evaluate_inquiry_to_order_progression(inquiry)
    assert ev2 == ev


def test_inquiry_to_order_not_blocked_when_gate_satisfied() -> None:
    svc = ProgressionService(InMemoryOrderRepository())
    assert svc.evaluate_inquiry_to_order_progression(_sample_inquiry()).blocked is False
    assert svc.evaluate_inquiry_to_order_progression(_sample_inquiry()).reasons == ()
    verified = replace(
        _sample_inquiry(),
        call_verification_required=True,
        call_verification_status="verified",
    )
    assert svc.evaluate_inquiry_to_order_progression(verified).blocked is False


def test_candidate_progression_blocked_when_candidate_missing() -> None:
    repo = InMemoryOrderRepository()
    prog = ProgressionService(repo)
    osvc = OrderService(repo)
    order, _v1 = osvc.convert_inquiry_to_order(_sample_inquiry())
    ev = prog.evaluate_candidate_version_progression(order.order_id)
    assert ev.blocked is True
    assert REASON_CANDIDATE_ORDER_VERSION_MISSING in ev.reasons


def test_candidate_progression_not_blocked_when_candidate_set() -> None:
    repo = InMemoryOrderRepository()
    prog = ProgressionService(repo)
    osvc = OrderService(repo)
    order, v1 = osvc.convert_inquiry_to_order(_sample_inquiry())
    osvc.set_candidate_order_version(order.order_id, v1.order_version_id)
    ev = prog.evaluate_candidate_version_progression(order.order_id)
    assert ev.blocked is False
    assert ev.reasons == ()


def test_candidate_progression_blocked_when_order_unknown() -> None:
    ev = ProgressionService(InMemoryOrderRepository()).evaluate_candidate_version_progression(
        "00000000-0000-0000-0000-000000000000"
    )
    assert ev.blocked is True
    assert REASON_ORDER_NOT_FOUND in ev.reasons


def test_candidate_progression_blocked_when_candidate_id_not_resolvable() -> None:
    repo = InMemoryOrderRepository()
    prog = ProgressionService(repo)
    osvc = OrderService(repo)
    order, v1 = osvc.convert_inquiry_to_order(_sample_inquiry())
    osvc.set_candidate_order_version(order.order_id, v1.order_version_id)
    del repo._versions[v1.order_version_id]
    ev = prog.evaluate_candidate_version_progression(order.order_id)
    assert ev.blocked is True
    assert REASON_CANDIDATE_ORDER_VERSION_NOT_RESOLVABLE in ev.reasons


def test_order_progression_view_composes_latest_candidate_and_blocked() -> None:
    repo = InMemoryOrderRepository()
    prog = ProgressionService(repo)
    osvc = OrderService(repo)
    order, v1 = osvc.convert_inquiry_to_order(_sample_inquiry())
    v2 = osvc.create_relevant_order_change_version(
        order,
        event_date=date(2026, 11, 2),
        time_window_text="abends",
        location_text="Berlin",
        guest_count_estimate=30,
        planning_mode=PLANNING_MODES[1],
    )
    osvc.set_candidate_order_version(order.order_id, v1.order_version_id)
    view = prog.get_order_progression_view(order.order_id)
    assert view is not None
    assert isinstance(view, OrderProgressionView)
    assert view.order_id == order.order_id
    assert view.latest_order_version is not None
    assert view.latest_order_version.order_version_id == v2.order_version_id
    assert view.candidate_order_version is not None
    assert view.candidate_order_version.order_version_id == v1.order_version_id
    ev = prog.evaluate_candidate_version_progression(order.order_id)
    assert view.blocked == ev.blocked
    assert view.reasons == ev.reasons
    assert view.blocked is False


def test_order_progression_view_when_candidate_absent() -> None:
    repo = InMemoryOrderRepository()
    prog = ProgressionService(repo)
    osvc = OrderService(repo)
    order, v1 = osvc.convert_inquiry_to_order(_sample_inquiry())
    view = prog.get_order_progression_view(order.order_id)
    assert view is not None
    assert view.latest_order_version is not None
    assert view.latest_order_version.order_version_id == v1.order_version_id
    assert view.candidate_order_version is None
    assert view.blocked is True
    assert REASON_CANDIDATE_ORDER_VERSION_MISSING in view.reasons


def test_order_progression_view_unknown_order_returns_none() -> None:
    assert (
        ProgressionService(InMemoryOrderRepository()).get_order_progression_view(
            "00000000-0000-0000-0000-000000000000"
        )
        is None
    )


def test_progression_decision_eligible_when_candidate_ok_and_not_blocked() -> None:
    repo = InMemoryOrderRepository()
    prog = ProgressionService(repo)
    osvc = OrderService(repo)
    order, v1 = osvc.convert_inquiry_to_order(_sample_inquiry())
    osvc.set_candidate_order_version(order.order_id, v1.order_version_id)
    d = prog.evaluate_order_progression_decision(order.order_id)
    assert isinstance(d, OrderProgressionDecision)
    assert d.eligible_for_progression_review is True
    assert d.reasons == ()
    assert d.candidate_order_version_id == v1.order_version_id


def test_progression_decision_not_eligible_when_candidate_missing() -> None:
    repo = InMemoryOrderRepository()
    prog = ProgressionService(repo)
    osvc = OrderService(repo)
    order, _v1 = osvc.convert_inquiry_to_order(_sample_inquiry())
    d = prog.evaluate_order_progression_decision(order.order_id)
    assert d.eligible_for_progression_review is False
    assert REASON_CANDIDATE_ORDER_VERSION_MISSING in d.reasons
    assert d.candidate_order_version_id is None


def test_progression_decision_not_eligible_when_candidate_not_resolvable() -> None:
    repo = InMemoryOrderRepository()
    prog = ProgressionService(repo)
    osvc = OrderService(repo)
    order, v1 = osvc.convert_inquiry_to_order(_sample_inquiry())
    osvc.set_candidate_order_version(order.order_id, v1.order_version_id)
    del repo._versions[v1.order_version_id]
    d = prog.evaluate_order_progression_decision(order.order_id)
    assert d.eligible_for_progression_review is False
    assert REASON_CANDIDATE_ORDER_VERSION_NOT_RESOLVABLE in d.reasons


def test_progression_decision_not_eligible_when_order_unknown() -> None:
    missing = "00000000-0000-0000-0000-000000000000"
    d = ProgressionService(InMemoryOrderRepository()).evaluate_order_progression_decision(missing)
    assert d.order_id == missing
    assert d.eligible_for_progression_review is False
    assert REASON_ORDER_NOT_FOUND in d.reasons
    assert d.candidate_order_version_id is None


def test_checkpoint_composes_view_and_decision() -> None:
    repo = InMemoryOrderRepository()
    prog = ProgressionService(repo)
    osvc = OrderService(repo)
    order, v1 = osvc.convert_inquiry_to_order(_sample_inquiry())
    v2 = osvc.create_relevant_order_change_version(
        order,
        event_date=date(2026, 11, 2),
        time_window_text="abends",
        location_text="Berlin",
        guest_count_estimate=30,
        planning_mode=PLANNING_MODES[1],
    )
    osvc.set_candidate_order_version(order.order_id, v1.order_version_id)
    cp = prog.get_order_progression_checkpoint(order.order_id)
    view = prog.get_order_progression_view(order.order_id)
    dec = prog.evaluate_order_progression_decision(order.order_id)
    assert cp is not None and view is not None
    assert isinstance(cp, OrderProgressionCheckpoint)
    assert cp.order_id == order.order_id
    assert cp.latest_order_version_id == v2.order_version_id
    assert cp.candidate_order_version_id == v1.order_version_id
    assert cp.blocked == view.blocked
    assert cp.reasons == view.reasons
    assert cp.eligible_for_progression_review == dec.eligible_for_progression_review


def test_checkpoint_when_candidate_absent() -> None:
    repo = InMemoryOrderRepository()
    prog = ProgressionService(repo)
    osvc = OrderService(repo)
    order, v1 = osvc.convert_inquiry_to_order(_sample_inquiry())
    cp = prog.get_order_progression_checkpoint(order.order_id)
    assert cp is not None
    assert cp.latest_order_version_id == v1.order_version_id
    assert cp.candidate_order_version_id is None
    assert cp.blocked is True
    assert REASON_CANDIDATE_ORDER_VERSION_MISSING in cp.reasons
    assert cp.eligible_for_progression_review is False


def test_checkpoint_unknown_order_returns_none() -> None:
    assert (
        ProgressionService(InMemoryOrderRepository()).get_order_progression_checkpoint(
            "00000000-0000-0000-0000-000000000000"
        )
        is None
    )


def test_progression_modules_have_no_kitchen_or_release_surface() -> None:
    import catering_system.domain.order_progression_checkpoint as opc_mod
    import catering_system.domain.order_progression_decision as opd_mod
    import catering_system.domain.order_progression_view as opv_mod
    import catering_system.domain.progression_blockers as pb_mod
    import catering_system.services.progression_service as ps_mod

    for mod in (pb_mod, ps_mod, opv_mod, opd_mod, opc_mod):
        lowered = _module_source_lower(mod)
        assert "kitchen" not in lowered
        assert "ready_to_send" not in lowered
        assert "wochen" not in lowered
        assert "kiosk" not in lowered
