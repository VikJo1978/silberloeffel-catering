"""Unit tests — Slice B7–B23 progression derived reads, export, status label, badges, severity, state signature, facts (derived)."""

from __future__ import annotations

import json
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
from catering_system.domain.order_progression_bundle import OrderProgressionBundle
from catering_system.domain.order_progression_debug_dict import order_progression_export_to_dict
from catering_system.domain.order_progression_json_debug import order_progression_debug_dict_to_json
from catering_system.domain.order_progression_export import OrderProgressionExport
from catering_system.domain.order_progression_facts import OrderProgressionFacts
from catering_system.domain.order_progression_badges import (
    OrderProgressionBadges,
    derive_order_progression_badges,
)
from catering_system.domain.order_progression_reason_codes import OrderProgressionReasonCodes
from catering_system.domain.order_progression_severity import (
    OrderProgressionSeverity,
    derive_order_progression_severity,
)
from catering_system.domain.order_progression_state_signature import (
    OrderProgressionStateSignature,
    derive_order_progression_state_signature,
)
from catering_system.domain.order_progression_status_label import (
    OrderProgressionStatusLabel,
    derive_order_progression_status_label,
)
from catering_system.domain.order_progression_text_summary import format_order_progression_export_text
from catering_system.domain.order_progression_checkpoint import OrderProgressionCheckpoint
from catering_system.domain.order_progression_consistency_check import (
    OrderProgressionConsistencyCheck,
    evaluate_order_progression_consistency,
)
from catering_system.domain.order_progression_review_summary import OrderProgressionReviewSummary
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


def test_review_summary_matches_checkpoint_and_reason_count() -> None:
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
    sm = prog.get_order_progression_review_summary(order.order_id)
    assert cp is not None and sm is not None
    assert isinstance(sm, OrderProgressionReviewSummary)
    assert sm.order_id == cp.order_id
    assert sm.latest_order_version_id == cp.latest_order_version_id == v2.order_version_id
    assert sm.candidate_order_version_id == cp.candidate_order_version_id == v1.order_version_id
    assert sm.blocked == cp.blocked
    assert sm.eligible_for_progression_review == cp.eligible_for_progression_review
    assert sm.reasons == cp.reasons
    assert sm.reason_count == len(cp.reasons)


def test_review_summary_when_candidate_absent() -> None:
    repo = InMemoryOrderRepository()
    prog = ProgressionService(repo)
    osvc = OrderService(repo)
    order, v1 = osvc.convert_inquiry_to_order(_sample_inquiry())
    sm = prog.get_order_progression_review_summary(order.order_id)
    assert sm is not None
    assert sm.latest_order_version_id == v1.order_version_id
    assert sm.candidate_order_version_id is None
    assert sm.blocked is True
    assert sm.eligible_for_progression_review is False
    assert REASON_CANDIDATE_ORDER_VERSION_MISSING in sm.reasons
    assert sm.reason_count == 1


def test_review_summary_unknown_order_returns_none() -> None:
    assert (
        ProgressionService(InMemoryOrderRepository()).get_order_progression_review_summary(
            "00000000-0000-0000-0000-000000000000"
        )
        is None
    )


def test_consistency_check_consistent_when_layers_align() -> None:
    repo = InMemoryOrderRepository()
    prog = ProgressionService(repo)
    osvc = OrderService(repo)
    order, v1 = osvc.convert_inquiry_to_order(_sample_inquiry())
    osvc.set_candidate_order_version(order.order_id, v1.order_version_id)
    cc = prog.get_order_progression_consistency_check(order.order_id)
    assert cc is not None
    assert isinstance(cc, OrderProgressionConsistencyCheck)
    assert cc.order_id == order.order_id
    assert cc.consistent is True
    assert cc.reasons == ()


def test_consistency_check_unknown_order_returns_none() -> None:
    assert (
        ProgressionService(InMemoryOrderRepository()).get_order_progression_consistency_check(
            "00000000-0000-0000-0000-000000000000"
        )
        is None
    )


def test_bundle_unknown_order_returns_none() -> None:
    assert (
        ProgressionService(InMemoryOrderRepository()).get_order_progression_bundle(
            "00000000-0000-0000-0000-000000000000"
        )
        is None
    )


def test_bundle_matches_individual_derived_getters() -> None:
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
    oid = order.order_id
    b = prog.get_order_progression_bundle(oid)
    view = prog.get_order_progression_view(oid)
    decision = prog.evaluate_order_progression_decision(oid)
    cp = prog.get_order_progression_checkpoint(oid)
    sm = prog.get_order_progression_review_summary(oid)
    cc = prog.get_order_progression_consistency_check(oid)
    assert b is not None and view is not None and cp is not None and sm is not None and cc is not None
    assert isinstance(b, OrderProgressionBundle)
    assert b.order_id == oid
    assert b.view == view
    assert b.decision == decision
    assert b.checkpoint == cp
    assert b.review_summary == sm
    assert b.consistency_check == cc
    assert b.view.latest_order_version is not None
    assert b.view.latest_order_version.order_version_id == v2.order_version_id


def test_export_unknown_order_returns_none() -> None:
    assert (
        ProgressionService(InMemoryOrderRepository()).get_order_progression_export(
            "00000000-0000-0000-0000-000000000000"
        )
        is None
    )


def test_export_flattened_from_bundle_checkpoint_and_consistency() -> None:
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
    oid = order.order_id
    b = prog.get_order_progression_bundle(oid)
    ex = prog.get_order_progression_export(oid)
    assert b is not None and ex is not None
    assert isinstance(ex, OrderProgressionExport)
    cp = b.checkpoint
    assert ex.order_id == oid
    assert ex.latest_order_version_id == cp.latest_order_version_id == v2.order_version_id
    assert ex.candidate_order_version_id == cp.candidate_order_version_id == v1.order_version_id
    assert ex.blocked == cp.blocked
    assert ex.eligible_for_progression_review == cp.eligible_for_progression_review
    assert ex.reasons == cp.reasons
    assert ex.reason_count == b.review_summary.reason_count == len(cp.reasons)
    assert ex.consistent is True
    assert ex.consistent == b.consistency_check.consistent


def test_text_summary_unknown_order_returns_none() -> None:
    assert (
        ProgressionService(InMemoryOrderRepository()).get_order_progression_text_summary(
            "00000000-0000-0000-0000-000000000000"
        )
        is None
    )


def test_text_summary_deterministic_from_export() -> None:
    repo = InMemoryOrderRepository()
    prog = ProgressionService(repo)
    osvc = OrderService(repo)
    order, v1 = osvc.convert_inquiry_to_order(_sample_inquiry())
    osvc.set_candidate_order_version(order.order_id, v1.order_version_id)
    oid = order.order_id
    ex = prog.get_order_progression_export(oid)
    txt = prog.get_order_progression_text_summary(oid)
    assert ex is not None and txt is not None
    assert txt == format_order_progression_export_text(ex)
    assert oid in txt
    assert "consistent: true" in txt


def test_format_order_progression_export_text_fixed_shape() -> None:
    ex = OrderProgressionExport(
        order_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        latest_order_version_id=None,
        candidate_order_version_id=None,
        blocked=True,
        eligible_for_progression_review=False,
        consistent=True,
        reason_count=1,
        reasons=("r-a",),
    )
    s = format_order_progression_export_text(ex)
    assert s == (
        "order_id: bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb\n"
        "latest_order_version_id: none\n"
        "candidate_order_version_id: none\n"
        "blocked: true\n"
        "eligible_for_progression_review: false\n"
        "consistent: true\n"
        "reason_count: 1\n"
        "reason[0]: r-a\n"
    )


def test_debug_dict_unknown_order_returns_none() -> None:
    assert (
        ProgressionService(InMemoryOrderRepository()).get_order_progression_debug_dict(
            "00000000-0000-0000-0000-000000000000"
        )
        is None
    )


def test_debug_dict_matches_export_builtin_types() -> None:
    repo = InMemoryOrderRepository()
    prog = ProgressionService(repo)
    osvc = OrderService(repo)
    order, v1 = osvc.convert_inquiry_to_order(_sample_inquiry())
    osvc.set_candidate_order_version(order.order_id, v1.order_version_id)
    oid = order.order_id
    ex = prog.get_order_progression_export(oid)
    d = prog.get_order_progression_debug_dict(oid)
    assert ex is not None and d is not None
    assert d == order_progression_export_to_dict(ex)
    assert d["order_id"] == ex.order_id
    assert d["latest_order_version_id"] == ex.latest_order_version_id
    assert d["candidate_order_version_id"] == ex.candidate_order_version_id
    assert d["blocked"] is ex.blocked
    assert d["eligible_for_progression_review"] is ex.eligible_for_progression_review
    assert d["consistent"] is ex.consistent
    assert d["reason_count"] == ex.reason_count
    assert d["reasons"] == list(ex.reasons)
    assert isinstance(d["reasons"], list)


def test_json_debug_unknown_order_returns_none() -> None:
    assert (
        ProgressionService(InMemoryOrderRepository()).get_order_progression_json_debug(
            "00000000-0000-0000-0000-000000000000"
        )
        is None
    )


def test_json_debug_round_trips_debug_dict() -> None:
    repo = InMemoryOrderRepository()
    prog = ProgressionService(repo)
    osvc = OrderService(repo)
    order, v1 = osvc.convert_inquiry_to_order(_sample_inquiry())
    osvc.set_candidate_order_version(order.order_id, v1.order_version_id)
    oid = order.order_id
    d = prog.get_order_progression_debug_dict(oid)
    js = prog.get_order_progression_json_debug(oid)
    assert d is not None and js is not None
    assert json.loads(js) == d
    assert js == order_progression_debug_dict_to_json(d)


def test_order_progression_debug_dict_to_json_deterministic() -> None:
    d: dict[str, object] = {
        "blocked": True,
        "candidate_order_version_id": None,
        "consistent": False,
        "eligible_for_progression_review": False,
        "latest_order_version_id": None,
        "order_id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
        "reason_count": 1,
        "reasons": ["x"],
    }
    assert order_progression_debug_dict_to_json(d) == (
        '{"blocked":true,"candidate_order_version_id":null,'
        '"consistent":false,"eligible_for_progression_review":false,'
        '"latest_order_version_id":null,"order_id":"cccccccc-cccc-cccc-cccc-cccccccccccc",'
        '"reason_count":1,"reasons":["x"]}'
    )


def test_reason_codes_unknown_order_returns_none() -> None:
    assert (
        ProgressionService(InMemoryOrderRepository()).get_order_progression_reason_codes(
            "00000000-0000-0000-0000-000000000000"
        )
        is None
    )


def test_reason_codes_matches_export_order_and_count() -> None:
    repo = InMemoryOrderRepository()
    prog = ProgressionService(repo)
    osvc = OrderService(repo)
    order, v1 = osvc.convert_inquiry_to_order(_sample_inquiry())
    osvc.set_candidate_order_version(order.order_id, v1.order_version_id)
    oid = order.order_id
    ex = prog.get_order_progression_export(oid)
    rc = prog.get_order_progression_reason_codes(oid)
    assert ex is not None and rc is not None
    assert isinstance(rc, OrderProgressionReasonCodes)
    assert rc == OrderProgressionReasonCodes.from_export(ex)
    assert rc.order_id == ex.order_id
    assert rc.reason_count == ex.reason_count
    assert rc.reasons == ex.reasons


def test_status_label_unknown_order_returns_none() -> None:
    assert (
        ProgressionService(InMemoryOrderRepository()).get_order_progression_status_label(
            "00000000-0000-0000-0000-000000000000"
        )
        is None
    )


def test_status_label_eligible_when_export_eligible_and_consistent() -> None:
    repo = InMemoryOrderRepository()
    prog = ProgressionService(repo)
    osvc = OrderService(repo)
    order, v1 = osvc.convert_inquiry_to_order(_sample_inquiry())
    osvc.set_candidate_order_version(order.order_id, v1.order_version_id)
    oid = order.order_id
    ex = prog.get_order_progression_export(oid)
    sl = prog.get_order_progression_status_label(oid)
    assert ex is not None and sl is not None
    assert isinstance(sl, OrderProgressionStatusLabel)
    assert sl.order_id == oid
    assert sl.status_label == "eligible"
    assert sl == OrderProgressionStatusLabel.from_export(ex)


def test_status_label_blocked_when_candidate_missing() -> None:
    repo = InMemoryOrderRepository()
    prog = ProgressionService(repo)
    osvc = OrderService(repo)
    order, _v1 = osvc.convert_inquiry_to_order(_sample_inquiry())
    sl = prog.get_order_progression_status_label(order.order_id)
    assert sl is not None
    assert sl.status_label == "blocked"


def test_badges_unknown_order_returns_none() -> None:
    assert (
        ProgressionService(InMemoryOrderRepository()).get_order_progression_badges(
            "00000000-0000-0000-0000-000000000000"
        )
        is None
    )


def test_badges_matches_export_derived_tuple() -> None:
    repo = InMemoryOrderRepository()
    prog = ProgressionService(repo)
    osvc = OrderService(repo)
    order, v1 = osvc.convert_inquiry_to_order(_sample_inquiry())
    osvc.set_candidate_order_version(order.order_id, v1.order_version_id)
    oid = order.order_id
    ex = prog.get_order_progression_export(oid)
    bg = prog.get_order_progression_badges(oid)
    assert ex is not None and bg is not None
    assert isinstance(bg, OrderProgressionBadges)
    assert bg.order_id == oid
    assert bg.badges == derive_order_progression_badges(ex)
    assert bg == OrderProgressionBadges.from_export(ex)


def test_badges_blocked_candidate_missing_has_reasons_present() -> None:
    repo = InMemoryOrderRepository()
    prog = ProgressionService(repo)
    osvc = OrderService(repo)
    order, _v1 = osvc.convert_inquiry_to_order(_sample_inquiry())
    bg = prog.get_order_progression_badges(order.order_id)
    assert bg is not None
    assert bg.badges == (
        "blocked",
        "consistent",
        "reasons_present",
    )


def test_derive_order_progression_badges_fixed_order_and_flags() -> None:
    ex = OrderProgressionExport(
        order_id="eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
        latest_order_version_id=None,
        candidate_order_version_id=None,
        blocked=True,
        eligible_for_progression_review=False,
        consistent=False,
        reason_count=2,
        reasons=("a", "b"),
    )
    assert derive_order_progression_badges(ex) == (
        "blocked",
        "inconsistent",
        "reasons_present",
    )


def test_severity_unknown_order_returns_none() -> None:
    assert (
        ProgressionService(InMemoryOrderRepository()).get_order_progression_severity(
            "00000000-0000-0000-0000-000000000000"
        )
        is None
    )


def test_severity_matches_export_derived_string() -> None:
    repo = InMemoryOrderRepository()
    prog = ProgressionService(repo)
    osvc = OrderService(repo)
    order, v1 = osvc.convert_inquiry_to_order(_sample_inquiry())
    osvc.set_candidate_order_version(order.order_id, v1.order_version_id)
    oid = order.order_id
    ex = prog.get_order_progression_export(oid)
    sv = prog.get_order_progression_severity(oid)
    assert ex is not None and sv is not None
    assert isinstance(sv, OrderProgressionSeverity)
    assert sv.order_id == oid
    assert sv.severity == derive_order_progression_severity(ex)
    assert sv == OrderProgressionSeverity.from_export(ex)
    assert sv.severity == "normal"


def test_severity_blocked_candidate_missing_is_high() -> None:
    repo = InMemoryOrderRepository()
    prog = ProgressionService(repo)
    osvc = OrderService(repo)
    order, _v1 = osvc.convert_inquiry_to_order(_sample_inquiry())
    sv = prog.get_order_progression_severity(order.order_id)
    assert sv is not None
    assert sv.severity == "high"


def test_derive_order_progression_severity_priority() -> None:
    assert (
        derive_order_progression_severity(
            OrderProgressionExport(
                order_id="ffffffff-ffff-ffff-ffff-ffffffffffff",
                latest_order_version_id=None,
                candidate_order_version_id=None,
                blocked=True,
                eligible_for_progression_review=False,
                consistent=False,
                reason_count=1,
                reasons=("x",),
            )
        )
        == "critical"
    )
    assert (
        derive_order_progression_severity(
            OrderProgressionExport(
                order_id="77777777-7777-7777-7777-777777777777",
                latest_order_version_id=None,
                candidate_order_version_id=None,
                blocked=True,
                eligible_for_progression_review=False,
                consistent=True,
                reason_count=1,
                reasons=("y",),
            )
        )
        == "high"
    )
    assert (
        derive_order_progression_severity(
            OrderProgressionExport(
                order_id="66666666-6666-6666-6666-666666666666",
                latest_order_version_id=None,
                candidate_order_version_id=None,
                blocked=False,
                eligible_for_progression_review=False,
                consistent=True,
                reason_count=1,
                reasons=("z",),
            )
        )
        == "elevated"
    )
    assert (
        derive_order_progression_severity(
            OrderProgressionExport(
                order_id="55555555-5555-5555-5555-555555555555",
                latest_order_version_id=None,
                candidate_order_version_id=None,
                blocked=False,
                eligible_for_progression_review=True,
                consistent=True,
                reason_count=0,
                reasons=(),
            )
        )
        == "normal"
    )
    assert (
        derive_order_progression_severity(
            OrderProgressionExport(
                order_id="44444444-4444-4444-4444-444444444444",
                latest_order_version_id=None,
                candidate_order_version_id=None,
                blocked=False,
                eligible_for_progression_review=False,
                consistent=True,
                reason_count=0,
                reasons=(),
            )
        )
        == "low"
    )


def test_state_signature_unknown_order_returns_none() -> None:
    assert (
        ProgressionService(InMemoryOrderRepository()).get_order_progression_state_signature(
            "00000000-0000-0000-0000-000000000000"
        )
        is None
    )


def test_state_signature_matches_export_derived_string() -> None:
    repo = InMemoryOrderRepository()
    prog = ProgressionService(repo)
    osvc = OrderService(repo)
    order, v1 = osvc.convert_inquiry_to_order(_sample_inquiry())
    osvc.set_candidate_order_version(order.order_id, v1.order_version_id)
    oid = order.order_id
    ex = prog.get_order_progression_export(oid)
    sig = prog.get_order_progression_state_signature(oid)
    assert ex is not None and sig is not None
    assert isinstance(sig, OrderProgressionStateSignature)
    assert sig.order_id == oid
    assert sig.state_signature == derive_order_progression_state_signature(ex)
    assert sig == OrderProgressionStateSignature.from_export(ex)


def test_state_signature_eligible_and_blocked_missing_shapes() -> None:
    repo = InMemoryOrderRepository()
    prog = ProgressionService(repo)
    osvc = OrderService(repo)
    order, v1 = osvc.convert_inquiry_to_order(_sample_inquiry())
    osvc.set_candidate_order_version(order.order_id, v1.order_version_id)
    sig_ok = prog.get_order_progression_state_signature(order.order_id)
    order2, _v1b = osvc.convert_inquiry_to_order(_sample_inquiry())
    sig_blocked = prog.get_order_progression_state_signature(order2.order_id)
    assert sig_ok is not None and sig_blocked is not None
    assert (
        sig_ok.state_signature
        == "blocked=false|eligible_for_progression_review=true|consistent=true|reason_count=0"
    )
    assert (
        sig_blocked.state_signature
        == "blocked=true|eligible_for_progression_review=false|consistent=true|reason_count=1"
    )


def test_derive_order_progression_state_signature_fixed_field_order() -> None:
    ex = OrderProgressionExport(
        order_id="33333333-3333-3333-3333-333333333333",
        latest_order_version_id=None,
        candidate_order_version_id=None,
        blocked=False,
        eligible_for_progression_review=False,
        consistent=False,
        reason_count=3,
        reasons=("a", "b", "c"),
    )
    assert (
        derive_order_progression_state_signature(ex)
        == "blocked=false|eligible_for_progression_review=false|consistent=false|reason_count=3"
    )


def test_facts_unknown_order_returns_none() -> None:
    assert (
        ProgressionService(InMemoryOrderRepository()).get_order_progression_facts(
            "00000000-0000-0000-0000-000000000000"
        )
        is None
    )


def test_facts_matches_from_export_eligible() -> None:
    repo = InMemoryOrderRepository()
    prog = ProgressionService(repo)
    osvc = OrderService(repo)
    order, v1 = osvc.convert_inquiry_to_order(_sample_inquiry())
    osvc.set_candidate_order_version(order.order_id, v1.order_version_id)
    oid = order.order_id
    ex = prog.get_order_progression_export(oid)
    facts = prog.get_order_progression_facts(oid)
    assert ex is not None and facts is not None
    assert isinstance(facts, OrderProgressionFacts)
    assert facts == OrderProgressionFacts.from_export(ex)
    assert facts.order_id == oid
    assert facts.has_reasons is (ex.reason_count > 0)
    assert facts.is_blocked is ex.blocked
    assert facts.is_consistent is ex.consistent
    assert facts.is_eligible is ex.eligible_for_progression_review
    assert facts.has_reasons is False
    assert facts.is_blocked is False
    assert facts.is_consistent is True
    assert facts.is_eligible is True


def test_facts_blocked_candidate_missing() -> None:
    repo = InMemoryOrderRepository()
    prog = ProgressionService(repo)
    osvc = OrderService(repo)
    order, _v1 = osvc.convert_inquiry_to_order(_sample_inquiry())
    facts = prog.get_order_progression_facts(order.order_id)
    assert facts is not None
    assert facts.has_reasons is True
    assert facts.is_blocked is True
    assert facts.is_consistent is True
    assert facts.is_eligible is False


def test_order_progression_facts_from_export_synthetic() -> None:
    ex = OrderProgressionExport(
        order_id="22222222-2222-2222-2222-222222222222",
        latest_order_version_id=None,
        candidate_order_version_id=None,
        blocked=False,
        eligible_for_progression_review=True,
        consistent=False,
        reason_count=0,
        reasons=(),
    )
    f = OrderProgressionFacts.from_export(ex)
    assert f.order_id == ex.order_id
    assert f.has_reasons is False
    assert f.is_blocked is False
    assert f.is_consistent is False
    assert f.is_eligible is True


def test_derive_order_progression_status_label_inconsistent_first() -> None:
    ex = OrderProgressionExport(
        order_id="dddddddd-dddd-dddd-dddd-dddddddddddd",
        latest_order_version_id=None,
        candidate_order_version_id=None,
        blocked=True,
        eligible_for_progression_review=False,
        consistent=False,
        reason_count=1,
        reasons=("x",),
    )
    assert derive_order_progression_status_label(ex) == "inconsistent"


def test_evaluate_order_progression_consistency_detects_mismatch() -> None:
    oid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    view = OrderProgressionView(
        order_id=oid,
        latest_order_version=None,
        candidate_order_version=None,
        blocked=True,
        reasons=(REASON_CANDIDATE_ORDER_VERSION_MISSING,),
    )
    decision = OrderProgressionDecision(
        order_id=oid,
        eligible_for_progression_review=False,
        reasons=(REASON_CANDIDATE_ORDER_VERSION_MISSING,),
        candidate_order_version_id=None,
    )
    checkpoint = OrderProgressionCheckpoint(
        order_id=oid,
        latest_order_version_id=None,
        candidate_order_version_id=None,
        blocked=False,
        reasons=(REASON_CANDIDATE_ORDER_VERSION_MISSING,),
        eligible_for_progression_review=False,
    )
    summary = OrderProgressionReviewSummary(
        order_id=oid,
        latest_order_version_id=None,
        candidate_order_version_id=None,
        blocked=False,
        eligible_for_progression_review=False,
        reason_count=1,
        reasons=(REASON_CANDIDATE_ORDER_VERSION_MISSING,),
    )
    out = evaluate_order_progression_consistency(oid, view, decision, checkpoint, summary)
    assert out.consistent is False
    assert "checkpoint.blocked != view.blocked" in out.reasons


def test_progression_modules_have_no_kitchen_or_release_surface() -> None:
    import catering_system.domain.order_progression_badges as opbadges_mod
    import catering_system.domain.order_progression_bundle as opb_mod
    import catering_system.domain.order_progression_severity as opsv_mod
    import catering_system.domain.order_progression_state_signature as opss_mod
    import catering_system.domain.order_progression_debug_dict as opdd_mod
    import catering_system.domain.order_progression_json_debug as opjd_mod
    import catering_system.domain.order_progression_export as ope_mod
    import catering_system.domain.order_progression_facts as opfacts_mod
    import catering_system.domain.order_progression_reason_codes as oprc_mod
    import catering_system.domain.order_progression_status_label as opsl_mod
    import catering_system.domain.order_progression_text_summary as opts_mod
    import catering_system.domain.order_progression_checkpoint as opc_mod
    import catering_system.domain.order_progression_consistency_check as opcc_mod
    import catering_system.domain.order_progression_decision as opd_mod
    import catering_system.domain.order_progression_review_summary as oprs_mod
    import catering_system.domain.order_progression_view as opv_mod
    import catering_system.domain.progression_blockers as pb_mod
    import catering_system.services.progression_service as ps_mod

    for mod in (
        pb_mod,
        ps_mod,
        opv_mod,
        opd_mod,
        opc_mod,
        oprs_mod,
        opcc_mod,
        opb_mod,
        ope_mod,
        opfacts_mod,
        opts_mod,
        opdd_mod,
        opjd_mod,
        oprc_mod,
        opsl_mod,
        opbadges_mod,
        opsv_mod,
        opss_mod,
    ):
        lowered = _module_source_lower(mod)
        assert "kitchen" not in lowered
        assert "ready_to_send" not in lowered
        assert "wochen" not in lowered
        assert "kiosk" not in lowered
