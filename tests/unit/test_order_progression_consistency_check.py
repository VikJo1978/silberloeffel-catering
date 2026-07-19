"""Unit tests for order progression consistency evaluation (Slice B12)."""

from __future__ import annotations

from datetime import date, datetime, timezone

from catering_system.domain.order import OrderVersion
from catering_system.domain.order_progression_checkpoint import (
    OrderProgressionCheckpoint,
)
from catering_system.domain.order_progression_consistency_check import (
    evaluate_order_progression_consistency,
)
from catering_system.domain.order_progression_decision import OrderProgressionDecision
from catering_system.domain.order_progression_review_summary import (
    OrderProgressionReviewSummary,
)
from catering_system.domain.order_progression_view import OrderProgressionView

_ORDER_ID = "11111111-1111-4111-8111-111111111111"
_VERSION_ID = "22222222-2222-4222-8222-222222222222"
_OTHER_VERSION = "33333333-3333-4333-8333-333333333333"
_NOW = datetime(2026, 7, 15, 10, 0, tzinfo=timezone.utc)


def _version(version_id: str = _VERSION_ID) -> OrderVersion:
    return OrderVersion(
        order_id=_ORDER_ID,
        order_version_id=version_id,
        version_number=1,
        created_at=_NOW,
        event_date=date(2026, 10, 1),
        time_window_text="mittags",
        location_text="Hamburg",
        guest_count_estimate=25,
        planning_mode="caterer_suggestion",
    )


def _aligned() -> tuple[
    OrderProgressionView,
    OrderProgressionDecision,
    OrderProgressionCheckpoint,
    OrderProgressionReviewSummary,
]:
    reasons = ("candidate_missing",)
    view = OrderProgressionView(
        order_id=_ORDER_ID,
        latest_order_version=_version(),
        candidate_order_version=None,
        blocked=True,
        reasons=reasons,
    )
    decision = OrderProgressionDecision(
        order_id=_ORDER_ID,
        eligible_for_progression_review=False,
        reasons=reasons,
        candidate_order_version_id=None,
    )
    checkpoint = OrderProgressionCheckpoint(
        order_id=_ORDER_ID,
        latest_order_version_id=_VERSION_ID,
        candidate_order_version_id=None,
        blocked=True,
        reasons=reasons,
        eligible_for_progression_review=False,
    )
    summary = OrderProgressionReviewSummary(
        order_id=_ORDER_ID,
        latest_order_version_id=_VERSION_ID,
        candidate_order_version_id=None,
        blocked=True,
        eligible_for_progression_review=False,
        reason_count=1,
        reasons=reasons,
    )
    return view, decision, checkpoint, summary


def test_consistent_bundle_reports_no_reasons() -> None:
    view, decision, checkpoint, summary = _aligned()
    result = evaluate_order_progression_consistency(
        _ORDER_ID, view, decision, checkpoint, summary
    )
    assert result.consistent is True
    assert result.reasons == ()


def test_view_order_id_mismatch_is_reported() -> None:
    view, decision, checkpoint, summary = _aligned()
    view = OrderProgressionView(
        order_id="00000000-0000-4000-8000-000000000000",
        latest_order_version=view.latest_order_version,
        candidate_order_version=None,
        blocked=True,
        reasons=view.reasons,
    )
    result = evaluate_order_progression_consistency(
        _ORDER_ID, view, decision, checkpoint, summary
    )
    assert result.consistent is False
    assert "view.order_id differs" in result.reasons[0]


def test_checkpoint_latest_version_mismatch_is_reported() -> None:
    view, decision, checkpoint, summary = _aligned()
    checkpoint = OrderProgressionCheckpoint(
        order_id=checkpoint.order_id,
        latest_order_version_id=_OTHER_VERSION,
        candidate_order_version_id=checkpoint.candidate_order_version_id,
        blocked=checkpoint.blocked,
        reasons=checkpoint.reasons,
        eligible_for_progression_review=checkpoint.eligible_for_progression_review,
    )
    result = evaluate_order_progression_consistency(
        _ORDER_ID, view, decision, checkpoint, summary
    )
    assert result.consistent is False
    assert any("latest_order_version_id" in reason for reason in result.reasons)


def test_summary_reason_count_mismatch_is_reported() -> None:
    view, decision, checkpoint, summary = _aligned()
    summary = OrderProgressionReviewSummary(
        order_id=summary.order_id,
        latest_order_version_id=summary.latest_order_version_id,
        candidate_order_version_id=summary.candidate_order_version_id,
        blocked=summary.blocked,
        eligible_for_progression_review=summary.eligible_for_progression_review,
        reason_count=99,
        reasons=summary.reasons,
    )
    result = evaluate_order_progression_consistency(
        _ORDER_ID, view, decision, checkpoint, summary
    )
    assert result.consistent is False
    assert any("reason_count" in reason for reason in result.reasons)


def test_all_mismatch_reasons_are_reported() -> None:
    view, decision, checkpoint, summary = _aligned()
    view = OrderProgressionView(
        order_id="00000000-0000-4000-8000-000000000000",
        latest_order_version=view.latest_order_version,
        candidate_order_version=None,
        blocked=True,
        reasons=("a", "b"),
    )
    decision = OrderProgressionDecision(
        order_id=_ORDER_ID,
        eligible_for_progression_review=False,
        reasons=("a",),
        candidate_order_version_id=None,
    )
    checkpoint = OrderProgressionCheckpoint(
        order_id=_ORDER_ID,
        latest_order_version_id=_VERSION_ID,
        candidate_order_version_id="00000000-0000-4000-8000-000000000099",
        blocked=False,
        reasons=("a", "b"),
        eligible_for_progression_review=True,
    )
    summary = OrderProgressionReviewSummary(
        order_id=_ORDER_ID,
        latest_order_version_id=_VERSION_ID,
        candidate_order_version_id=None,
        blocked=True,
        eligible_for_progression_review=False,
        reason_count=1,
        reasons=("a",),
    )
    result = evaluate_order_progression_consistency(
        _ORDER_ID, view, decision, checkpoint, summary
    )
    assert result.consistent is False
    assert len(result.reasons) >= 5


def test_decision_order_id_mismatch_is_reported() -> None:
    view, decision, checkpoint, summary = _aligned()
    decision = OrderProgressionDecision(
        order_id="00000000-0000-4000-8000-000000000000",
        eligible_for_progression_review=decision.eligible_for_progression_review,
        reasons=decision.reasons,
        candidate_order_version_id=decision.candidate_order_version_id,
    )
    result = evaluate_order_progression_consistency(
        _ORDER_ID, view, decision, checkpoint, summary
    )
    assert result.consistent is False
    assert any("decision.order_id differs" in reason for reason in result.reasons)


def test_checkpoint_order_id_mismatch_is_reported() -> None:
    view, decision, checkpoint, summary = _aligned()
    checkpoint = OrderProgressionCheckpoint(
        order_id="00000000-0000-4000-8000-000000000000",
        latest_order_version_id=checkpoint.latest_order_version_id,
        candidate_order_version_id=checkpoint.candidate_order_version_id,
        blocked=checkpoint.blocked,
        reasons=checkpoint.reasons,
        eligible_for_progression_review=checkpoint.eligible_for_progression_review,
    )
    result = evaluate_order_progression_consistency(
        _ORDER_ID, view, decision, checkpoint, summary
    )
    assert result.consistent is False
    assert any("checkpoint.order_id differs" in reason for reason in result.reasons)


def test_summary_order_id_mismatch_is_reported() -> None:
    view, decision, checkpoint, summary = _aligned()
    summary = OrderProgressionReviewSummary(
        order_id="00000000-0000-4000-8000-000000000000",
        latest_order_version_id=summary.latest_order_version_id,
        candidate_order_version_id=summary.candidate_order_version_id,
        blocked=summary.blocked,
        eligible_for_progression_review=summary.eligible_for_progression_review,
        reason_count=summary.reason_count,
        reasons=summary.reasons,
    )
    result = evaluate_order_progression_consistency(
        _ORDER_ID, view, decision, checkpoint, summary
    )
    assert result.consistent is False
    assert any("summary.order_id differs" in reason for reason in result.reasons)


def test_checkpoint_latest_mismatch_when_view_has_no_latest() -> None:
    view, decision, checkpoint, summary = _aligned()
    view = OrderProgressionView(
        order_id=_ORDER_ID,
        latest_order_version=None,
        candidate_order_version=None,
        blocked=True,
        reasons=view.reasons,
    )
    result = evaluate_order_progression_consistency(
        _ORDER_ID, view, decision, checkpoint, summary
    )
    assert result.consistent is False
    assert any("latest_order_version_id" in reason for reason in result.reasons)
