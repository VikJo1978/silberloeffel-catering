"""Progression blocked-state (B7), view (B8), decision (B9), checkpoint (B10), review summary (B11), consistency (B12), bundle (B13), export (B14) — derived only."""

from __future__ import annotations

from catering_system.domain.order import OrderVersion
from catering_system.domain.order_progression_bundle import OrderProgressionBundle
from catering_system.domain.order_progression_export import OrderProgressionExport
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
    REASON_ORDER_NOT_FOUND,
    ProgressionEvaluation,
    evaluate_inquiry_to_order_progression,
)
from catering_system.domain.inquiry import Inquiry
from catering_system.repositories.order_repository import OrderRepository


class ProgressionService:
    """Derives progression reads, bundle, and flat export DTO; no release-side logic."""

    def __init__(self, order_repository: OrderRepository) -> None:
        self._order_repository = order_repository

    def evaluate_inquiry_to_order_progression(self, inquiry: Inquiry) -> ProgressionEvaluation:
        """B7: explicit read for inquiry→order gate (same facts as B5)."""
        return evaluate_inquiry_to_order_progression(inquiry)

    def evaluate_candidate_version_progression(self, order_id: str) -> ProgressionEvaluation:
        """B7: candidate-based progression blocked when candidate missing or not resolvable."""
        order = self._order_repository.get_order(order_id)
        if order is None:
            return ProgressionEvaluation(blocked=True, reasons=(REASON_ORDER_NOT_FOUND,))
        cid = order.candidate_order_version_id
        if not cid:
            return ProgressionEvaluation(
                blocked=True,
                reasons=(REASON_CANDIDATE_ORDER_VERSION_MISSING,),
            )
        ver = self._order_repository.get_order_version(cid)
        if ver is None or ver.order_id != order_id:
            return ProgressionEvaluation(
                blocked=True,
                reasons=(REASON_CANDIDATE_ORDER_VERSION_NOT_RESOLVABLE,),
            )
        return ProgressionEvaluation(blocked=False, reasons=())

    def get_order_progression_view(self, order_id: str) -> OrderProgressionView | None:
        """B8: one composed read — latest history, resolvable candidate row, B7 candidate-progression evaluation."""
        if self._order_repository.get_order(order_id) is None:
            return None
        rows = self._order_repository.list_order_versions(order_id)
        latest: OrderVersion | None = rows[-1] if rows else None
        order = self._order_repository.get_order(order_id)
        assert order is not None
        candidate: OrderVersion | None = None
        cid = order.candidate_order_version_id
        if cid:
            v = self._order_repository.get_order_version(cid)
            if v is not None and v.order_id == order_id:
                candidate = v
        ev = self.evaluate_candidate_version_progression(order_id)
        return OrderProgressionView(
            order_id=order_id,
            latest_order_version=latest,
            candidate_order_version=candidate,
            blocked=ev.blocked,
            reasons=ev.reasons,
        )

    def evaluate_order_progression_decision(self, order_id: str) -> OrderProgressionDecision:
        """B9: office-side eligibility — derived from candidate presence/resolution and B7 blocked evaluation."""
        ev = self.evaluate_candidate_version_progression(order_id)
        order = self._order_repository.get_order(order_id)
        cid = order.candidate_order_version_id if order is not None else None
        eligible = not ev.blocked
        reasons: tuple[str, ...] = ev.reasons if ev.blocked else ()
        return OrderProgressionDecision(
            order_id=order_id,
            eligible_for_progression_review=eligible,
            reasons=reasons,
            candidate_order_version_id=cid,
        )

    def get_order_progression_checkpoint(self, order_id: str) -> OrderProgressionCheckpoint | None:
        """B10: on-demand snapshot from B8 view + B9 decision only; None if order unknown."""
        view = self.get_order_progression_view(order_id)
        if view is None:
            return None
        decision = self.evaluate_order_progression_decision(order_id)
        latest_id = (
            view.latest_order_version.order_version_id
            if view.latest_order_version is not None
            else None
        )
        return OrderProgressionCheckpoint(
            order_id=order_id,
            latest_order_version_id=latest_id,
            candidate_order_version_id=decision.candidate_order_version_id,
            blocked=view.blocked,
            reasons=view.reasons,
            eligible_for_progression_review=decision.eligible_for_progression_review,
        )

    def get_order_progression_review_summary(self, order_id: str) -> OrderProgressionReviewSummary | None:
        """B11: compact inspection summary from B10 checkpoint only; None if order unknown."""
        cp = self.get_order_progression_checkpoint(order_id)
        if cp is None:
            return None
        return OrderProgressionReviewSummary(
            order_id=cp.order_id,
            latest_order_version_id=cp.latest_order_version_id,
            candidate_order_version_id=cp.candidate_order_version_id,
            blocked=cp.blocked,
            eligible_for_progression_review=cp.eligible_for_progression_review,
            reason_count=len(cp.reasons),
            reasons=cp.reasons,
        )

    def get_order_progression_consistency_check(self, order_id: str) -> OrderProgressionConsistencyCheck | None:
        """B12: agreement across B8 view, B9 decision, B10 checkpoint, B11 summary; None if order unknown."""
        view = self.get_order_progression_view(order_id)
        if view is None:
            return None
        decision = self.evaluate_order_progression_decision(order_id)
        cp = self.get_order_progression_checkpoint(order_id)
        sm = self.get_order_progression_review_summary(order_id)
        assert cp is not None and sm is not None
        return evaluate_order_progression_consistency(order_id, view, decision, cp, sm)

    def get_order_progression_bundle(self, order_id: str) -> OrderProgressionBundle | None:
        """B13: one read-only bundle of B8 view, B9 decision, B10 checkpoint, B11 summary, B12 consistency; None if order unknown."""
        view = self.get_order_progression_view(order_id)
        if view is None:
            return None
        decision = self.evaluate_order_progression_decision(order_id)
        cp = self.get_order_progression_checkpoint(order_id)
        sm = self.get_order_progression_review_summary(order_id)
        cc = self.get_order_progression_consistency_check(order_id)
        assert cp is not None and sm is not None and cc is not None
        return OrderProgressionBundle(
            order_id=order_id,
            view=view,
            decision=decision,
            checkpoint=cp,
            review_summary=sm,
            consistency_check=cc,
        )

    def get_order_progression_export(self, order_id: str) -> OrderProgressionExport | None:
        """B14: flat export from B13 bundle only; None if order unknown."""
        b = self.get_order_progression_bundle(order_id)
        if b is None:
            return None
        return OrderProgressionExport.from_bundle(b)
