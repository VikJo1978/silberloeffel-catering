"""Derived progression blocked-state — Slice B7 (not a stored truth axis)."""

from __future__ import annotations

from dataclasses import dataclass

from catering_system.domain.inquiry import (
    Inquiry,
    inquiry_delivery_context_resolved,
)
from catering_system.domain.inquiry_contact_completeness import (
    derive_inquiry_contact_completeness,
)

# Narrow reason codes for office/Core evaluation only; not production-floor or release semantics.
REASON_INQUIRY_CALL_VERIFICATION_UNSATISFIED = "inquiry_call_verification_unsatisfied"
REASON_INQUIRY_REJECTED = "inquiry_rejected"
REASON_INQUIRY_DELIVERY_CONTEXT_UNRESOLVED = "inquiry_delivery_context_unresolved"
REASON_INQUIRY_CONTACT_MISSING_EMAIL = "inquiry_contact_missing_email"
REASON_INQUIRY_CONTACT_MISSING_PHONE = "inquiry_contact_missing_phone"
REASON_INQUIRY_CONTACT_MISSING_EMAIL_AND_PHONE = (
    "inquiry_contact_missing_email_and_phone"
)

_CONTACT_REASONS = {
    "missing_email": REASON_INQUIRY_CONTACT_MISSING_EMAIL,
    "missing_phone": REASON_INQUIRY_CONTACT_MISSING_PHONE,
    "missing_email_and_phone": REASON_INQUIRY_CONTACT_MISSING_EMAIL_AND_PHONE,
}
REASON_ORDER_NOT_FOUND = "order_not_found"
REASON_CANDIDATE_ORDER_VERSION_MISSING = "candidate_order_version_missing"
REASON_CANDIDATE_ORDER_VERSION_NOT_RESOLVABLE = "candidate_order_version_not_resolvable"


@dataclass(frozen=True)
class ProgressionEvaluation:
    """Derived from existing model facts; not persisted operational state."""

    blocked: bool
    reasons: tuple[str, ...] = ()


def evaluate_inquiry_to_order_progression(inquiry: Inquiry) -> ProgressionEvaluation:
    """Derive the inquiry → order blockers from the same facts as the Core gates.

    Keep the delivery-context reason distinct from call verification. Offer
    preparation intentionally filters only the pre-offer blockers, so an
    unresolved delivery address can still be resolved in the configurator
    before a customer-facing offer is finalized.
    """
    reasons: list[str] = []
    if inquiry.crm_stage == "Abgelehnt / verloren":
        reasons.append(REASON_INQUIRY_REJECTED)
    elif (
        inquiry.call_verification_required
        and inquiry.call_verification_status != "verified"
    ):
        reasons.append(REASON_INQUIRY_CALL_VERIFICATION_UNSATISFIED)
    elif not inquiry_delivery_context_resolved(inquiry):
        reasons.append(REASON_INQUIRY_DELIVERY_CONTEXT_UNRESOLVED)

    completeness = derive_inquiry_contact_completeness(inquiry)
    if completeness != "complete":
        reasons.append(_CONTACT_REASONS[completeness])
    if not reasons:
        return ProgressionEvaluation(blocked=False, reasons=())
    return ProgressionEvaluation(blocked=True, reasons=tuple(reasons))
