"""Unit tests — Slice B27 composed derived review summary (aggregates checkpoint + B21/B23–B25 only)."""

from __future__ import annotations

from tests.helpers.order_seed import seed_order

from datetime import date, datetime, timezone

from catering_system.domain.inquiry import (
    CALL_VERIFICATION_STATUSES,
    CRM_PIPELINE,
    Inquiry,
    PLANNING_MODES,
)
from catering_system.repositories.in_memory_order_repository import (
    InMemoryOrderRepository,
)
from catering_system.services.order_service import OrderService
from catering_system.services.progression_service import ProgressionService

from catering_system.domain.inquiry_customer_snapshot import (
    InquiryCustomerSnapshot as _CCSnapshot,
)

_CONTACT_COMPLETE_SNAPSHOT = _CCSnapshot(
    email="kunde@example.com", phone="+49301234567"
)


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
        customer_snapshot=_CONTACT_COMPLETE_SNAPSHOT,
    )


def test_composed_derived_review_unknown_order_returns_none() -> None:
    assert (
        ProgressionService(
            InMemoryOrderRepository()
        ).get_order_progression_composed_derived_review_summary(
            "00000000-0000-0000-0000-000000000000"
        )
        is None
    )


def test_composed_derived_review_eligible_matches_checkpoint_and_derived_getters() -> (
    None
):
    repo = InMemoryOrderRepository()
    prog = ProgressionService(repo)
    osvc = OrderService(repo)
    order, v1 = seed_order(repo, _sample_inquiry())
    osvc.set_candidate_order_version(order.order_id, v1.order_version_id)
    oid = order.order_id
    cp = prog.get_order_progression_checkpoint(oid)
    sv = prog.get_order_progression_severity(oid)
    rfp = prog.get_order_progression_reason_fingerprint(oid)
    rf = prog.get_order_progression_readiness_flags(oid)
    facts = prog.get_order_progression_facts(oid)
    comp = prog.get_order_progression_composed_derived_review_summary(oid)
    assert (
        cp is not None
        and sv is not None
        and rfp is not None
        and rf is not None
        and facts is not None
    )
    assert comp is not None
    assert comp.order_id == oid
    assert comp.latest_order_version_id == cp.latest_order_version_id
    assert comp.candidate_order_version_id == cp.candidate_order_version_id
    assert comp.blocked == cp.blocked
    assert comp.severity == sv.severity
    assert comp.reason_fingerprint == rfp.reason_fingerprint
    assert comp.readiness_flags == rf
    assert comp.facts_count == sum(
        1
        for v in (
            facts.has_reasons,
            facts.is_blocked,
            facts.is_consistent,
            facts.is_eligible,
        )
        if v
    )


def test_composed_derived_review_blocked_candidate_missing_matches_parts() -> None:
    repo = InMemoryOrderRepository()
    prog = ProgressionService(repo)
    OrderService(repo)
    order, _v1 = seed_order(repo, _sample_inquiry())
    oid = order.order_id
    cp = prog.get_order_progression_checkpoint(oid)
    sv = prog.get_order_progression_severity(oid)
    rfp = prog.get_order_progression_reason_fingerprint(oid)
    rf = prog.get_order_progression_readiness_flags(oid)
    facts = prog.get_order_progression_facts(oid)
    comp = prog.get_order_progression_composed_derived_review_summary(oid)
    assert cp is not None and comp is not None and facts is not None
    assert comp.blocked is True
    assert comp.blocked == cp.blocked
    assert comp.latest_order_version_id == cp.latest_order_version_id
    assert comp.candidate_order_version_id == cp.candidate_order_version_id
    assert comp.severity == sv.severity
    assert comp.reason_fingerprint == rfp.reason_fingerprint
    assert comp.readiness_flags == rf
    assert comp.facts_count == sum(
        1
        for v in (
            facts.has_reasons,
            facts.is_blocked,
            facts.is_consistent,
            facts.is_eligible,
        )
        if v
    )


def test_composed_derived_review_facts_count_matches_b23_flags_only() -> None:
    repo = InMemoryOrderRepository()
    prog = ProgressionService(repo)
    OrderService(repo)
    order, _v1 = seed_order(repo, _sample_inquiry())
    oid = order.order_id
    facts = prog.get_order_progression_facts(oid)
    comp = prog.get_order_progression_composed_derived_review_summary(oid)
    assert facts is not None and comp is not None
    expected = sum(
        1
        for v in (
            facts.has_reasons,
            facts.is_blocked,
            facts.is_consistent,
            facts.is_eligible,
        )
        if v
    )
    assert comp.facts_count == expected


def test_composed_derived_review_no_mutations_on_repo() -> None:
    repo = InMemoryOrderRepository()
    prog = ProgressionService(repo)
    osvc = OrderService(repo)
    order, v1 = seed_order(repo, _sample_inquiry())
    osvc.set_candidate_order_version(order.order_id, v1.order_version_id)
    oid = order.order_id
    before = len(repo._orders)
    _ = prog.get_order_progression_composed_derived_review_summary(oid)
    assert len(repo._orders) == before
