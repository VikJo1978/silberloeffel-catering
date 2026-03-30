"""Derived progression blocked-state — Slice B7 (not a stored truth axis)."""

from __future__ import annotations

from dataclasses import dataclass

from catering_system.domain.inquiry import Inquiry, inquiry_allows_order_conversion

# Narrow reason codes for office/Core evaluation only; not production-floor or release semantics.
REASON_INQUIRY_CALL_VERIFICATION_UNSATISFIED = "inquiry_call_verification_unsatisfied"
REASON_ORDER_NOT_FOUND = "order_not_found"
REASON_CANDIDATE_ORDER_VERSION_MISSING = "candidate_order_version_missing"
REASON_CANDIDATE_ORDER_VERSION_NOT_RESOLVABLE = "candidate_order_version_not_resolvable"


@dataclass(frozen=True)
class ProgressionEvaluation:
    """Derived from existing model facts; not persisted operational state."""

    blocked: bool
    reasons: tuple[str, ...] = ()


def evaluate_inquiry_to_order_progression(inquiry: Inquiry) -> ProgressionEvaluation:
    """B7: inquiry → order path blocked when B5 verification gate is not satisfied."""
    if inquiry_allows_order_conversion(inquiry):
        return ProgressionEvaluation(blocked=False, reasons=())
    return ProgressionEvaluation(
        blocked=True,
        reasons=(REASON_INQUIRY_CALL_VERIFICATION_UNSATISFIED,),
    )
