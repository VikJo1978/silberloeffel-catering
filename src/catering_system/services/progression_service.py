"""Progression blocked-state (B7) and composed progression read (B8) — Core/office-side derived only."""

from __future__ import annotations

from catering_system.domain.order import OrderVersion
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
    """Derives progression facts and composed views from inquiry/order data; no release-side logic."""

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
